'''
Template Component main class.

'''
import csv
import logging
from datetime import datetime, timedelta
import pytz
from typing import List, Dict

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement

from client.client import CNBRatesClient, CNBRatesClientException
from configuration import Configuration, ConfigurationException


CURRENCIES = {
    "Australian dollar": "AUD",
    "Brazilian real": "BRL",
    "Bulgarian lev": "BGN",
    "Chinese yuan renminbi": "CNY",
    "Danish krone": "DKK",
    "Euro": "EUR",
    "Philippine peso": "PHP",
    "Hong Kong dollar": "HKD",
    "Croatian kuna": "HRK",
    "Indian rupee": "INR",
    "Indonesian rupiah": "IDR",
    "Icelandic krona": "ISK",
    "Israeli shekel": "ILS",
    "Japanese yen": "JPY",
    "South African rand": "ZAR",
    "Canadian dollar": "CAD",
    "South Korean won": "KRW",
    "Hungarian forint": "HUF",
    "Malaysian ringgit": "MYR",
    "Mexican peso": "MXN",
    "Special drawing rights": "XDR",
    "Norwegian krone": "NOK",
    "New Zealand dollar": "NZD",
    "Polish zloty": "PLN",
    "Romanian leu": "RON",
    "Singapore dollar": "SGD",
    "Swedish krona": "SEK",
    "Swiss franc": "CHF",
    "Thai baht": "THB",
    "Turkish lira": "TRY",
    "US dollar": "USD",
    "Pound sterling": "GBP"
}


class Component(ComponentBase):
    def __init__(self):
        super().__init__()
        self.client = None

    # Date range setters
    @staticmethod
    def _set_date_range(dates_list: List, day: datetime, days: int) -> None:
        for i in range(days):
            dates_list.append(day - timedelta(days=i))

    def _set_today(self, dates_list: List, today: datetime) -> None:
        self._set_date_range(dates_list, today, 1)

    def _set_today_and_yesterday(self, dates_list: List, today: datetime) -> None:
        self._set_date_range(dates_list, today, 2)

    def _set_week(self, dates_list: List, today: datetime) -> None:
        self._set_date_range(dates_list, today, 7)

    @staticmethod
    def _set_custom_date_range(
        dates_list: list,
        today: datetime,
        date_from: datetime,
        date_to: datetime
    ) -> None:

        if date_from >= date_to:
            raise UserException('\"Date from\" is higher or equal to date to!')

        if date_from > today:
            raise UserException('\"Date from\" is in the future!')

        for i in range((min(date_to, today) - date_from).days + 1):
            dates_list.append(date_from + timedelta(days=i))

        if date_to > today:
            logging.warning(
                'For "Date to" you selected a day in the future! Therefore, '
                '"Date to" was set to today\'s day.'
            )

    # Date setters dictionary
    # Keys represents values of "dates" option in the config.json
    @property
    def _get_dates_setters(self) -> Dict[str, callable]:
        return {
            'Current day (currently declared rates)': self._set_today,
            'Current day and yesterday': self._set_today_and_yesterday,
            'Week': self._set_week,
            'Custom date range': self._set_custom_date_range
        }

    # Component specific methods
    @sync_action("list_currencies")
    def list_currencies(self) -> List[SelectElement]:
        return [SelectElement(label=k, value=v) for k, v in CURRENCIES.items()]

    def run(self):
        self.client = CNBRatesClient()
        params = Configuration(**self.configuration.parameters)

        dates_list = []
        today = datetime.now(pytz.timezone('Europe/Prague')).date()

        date_action = self._get_dates_setters.get(params.date_settings.dates)
        if date_action:
            if params.date_settings.dates == "Custom date range":
                try:
                    date_from = datetime.strptime(params.date_settings.dependent_date_from, '%Y-%m-%d').date()
                    date_to = datetime.strptime(params.date_settings.dependent_date_to, '%Y-%m-%d').date()
                    date_action(dates_list, today, date_from, date_to)
                except ValueError:
                    raise UserException('Dates not specified correctly for custom date range!')
            else:
                date_action(dates_list, today)

        file_header = ['date', 'country', 'currency', 'amount', 'code', 'rate']

        rates = self.client.get_rates(
            dates_list,
            today,
            params.date_settings.current_as_today,
            params.currencies.selected_currencies
        )

        table = self.create_out_table_definition(
            name='output.csv',
            incremental=params.incremental,
            primary_key=['date', 'code']
        )

        if rates:
            with open(table.full_path, mode='wt', encoding='utf-8', newline='') as out_file:
                writer = csv.writer(out_file)
                writer.writerow(file_header)
                writer.writerows(rates)
        else:
            raise UserException("Data were not fetched!")

        # Save table manifest (output.csv.manifest) from the tabledefinition
        self.write_manifest(table)


if __name__ == "__main__":
    try:
        comp = Component()
        # this triggers the run method by default and is controlled by the configuration.action parameter
        comp.execute_action()

    except (CNBRatesClientException, ConfigurationException) as exc:
        raise UserException(exc)

    except UserException as exc:
        logging.exception(exc)
        exit(1)

    except Exception as exc:
        logging.exception(exc)
        exit(2)
