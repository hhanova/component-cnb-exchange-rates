'''
Template Component main class.

'''
import csv
import logging
from datetime import datetime, timedelta
import pytz
import time
from typing import List, Dict

from keboola.component.base import ComponentBase
from keboola.component.exceptions import UserException

from .client import CNBRatesClient, CNBRatesClientException

# configuration variables
KEY_API_TOKEN = '#api_token'
KEY_PRINT_HELLO = 'print_hello'

# cnb endpoint and request tries variables
REQUEST_TRIES = 10
TARGET = 'https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt'

# list of mandatory parameters => if some is missing,
# component will fail with readable message on initialization.
REQUIRED_PARAMETERS = [KEY_PRINT_HELLO]
REQUIRED_IMAGE_PARS = []


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

    def run(self):
        logging.info('Running...')

        self.client = CNBRatesClient()
        start_time = time.time()
        # config.json parameters
        params = self.configuration.parameters

        out_table_name = params.get('file_name')
        if not out_table_name:
            raise UserException('You have to specify a name for the output table!')

        out_storage_path = 'in.c-cnb-extractor.' + out_table_name
        out_incremental = params['incremental']

        # output file definition - use if output mapping is enabled
        # kbc_out_path = self.configuration.config_data["storage"]["output"]["tables"][0]["destination"]
        # out_file_name = self.configuration.config_data["storage"]["output"]["tables"][0]["source"]
        # out_incremental = self.configuration.config_data["storage"]["output"]["tables"][0]["incremental"]

        dates_list = []
        today = datetime.now(pytz.timezone('Europe/Prague')).date()

        date_action = self._get_dates_setters.get(params['dates'])
        if date_action:
            if params['dates'] == "Custom date range":
                try:
                    date_from = datetime.strptime(params['dependent_date_from'], '%Y-%m-%d').date()
                    date_to = datetime.strptime(params['dependent_date_to'], '%Y-%m-%d').date()
                    date_action(dates_list, today, date_from, date_to)
                except ValueError:
                    raise UserException('Dates not specified correctly for custom date range!')
            else:
                date_action(dates_list, today)

        selected_currency = None if params['currency'] == 'All' else [
            p.split('_')[2] for p in params if p.startswith("select_curr") and params[p]
        ]

        if selected_currency == []:
            raise UserException('No currency was selected!')

        file_header = ['date', 'country', 'currency', 'amount', 'code', 'rate']

        rates = self.client.get_rates(
            dates_list,
            today,
            params['current_as_today'],
            selected_currency
        )

        table = self.create_out_table_definition(
            name='output.csv',
            destination=out_storage_path,
            incremental=out_incremental,
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

        # Write new state - will be available next run
        self.write_state_file({"some_state_parameter": "value"})
        end_time = time.time()
        logging.info(f'Execution time: {end_time - start_time} seconds')


if __name__ == "__main__":
    try:
        comp = Component()
        # this triggers the run method by default and is controlled by the configuration.action parameter
        comp.execute_action()

    except CNBRatesClientException as exc:
        raise UserException(exc)

    except UserException as exc:
        logging.exception(exc)
        exit(1)

    except Exception as exc:
        logging.exception(exc)
        exit(2)
