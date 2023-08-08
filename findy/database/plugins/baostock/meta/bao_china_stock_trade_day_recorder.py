# -*- coding: utf-8 -*-
from datetime import datetime

import pandas as pd

from findy.interface import Region, Provider
from findy.database.schema.meta.stock_meta import Stock
from findy.database.schema.quotes.trade_day import StockTradeDay
from findy.database.recorder import RecorderForEntities
from findy.database.persist import df_to_db
from findy.utils.functool import time_it
from findy.utils.time import PD_TIME_FORMAT_DAY, to_time_str
from findy.utils.pd import pd_valid

import findy.vendor.baostock as bs
try:
    bs.login()
except:
    pass


class BaoChinaStockTradeDayRecorder(RecorderForEntities):
    region = Region.CHN
    provider = Provider.BaoStock
    entity_schema = Stock
    data_schema = StockTradeDay

    async def init_entities(self, db_session):
        return ['stock_sz_000001']

    def generate_domain_id(self, entity, df, time_fmt=PD_TIME_FORMAT_DAY):
        return df['timestamp'].dt.strftime(time_fmt)

    @time_it
    async def eval(self, entity, http_session, db_session):
        return not isinstance(entity, str), None

    def bao_get_trade_days(self, start_date=None, end_date=None):
        def _bao_get_trade_days(start_date=None, end_date=None):
            k_rs = bs.query_trade_dates(start_date=start_date, end_date=end_date)
            return k_rs.get_data()

        try:
            return _bao_get_trade_days(start_date=start_date, end_date=end_date)
        except Exception as e:
            self.logger.error(f'bao_get_trade_days, error: {e}')
        return None

    @time_it
    async def record(self, entity, http_session, db_session, para):
        trade_day, column_names = StockTradeDay.query_data(
            region=self.region,
            provider=self.provider,
            db_session=db_session,
            order=StockTradeDay.timestamp.desc(),
            limit=1)

        start = to_time_str(trade_day[0].timestamp) if trade_day and len(trade_day) > 0 else "1990-12-19"

        df = self.bao_get_trade_days(start_date=start)

        if pd_valid(df):
            return False, self.format(entity, df)

        return True, None

    def format(self, entity, df):
        dates = df[df['is_trading_day'] == '1']['calendar_date'].values
        df = pd.DataFrame(dates, columns=['timestamp'])

        if not isinstance(df['timestamp'].dtypes, datetime):
            df['timestamp'] = pd.to_datetime(df['timestamp'])

        df['entity_id'] = 'stock_sz_000001'
        df['provider'] = self.provider.value
        df['id'] = self.generate_domain_id(entity, df)
        return df

    @time_it
    async def persist(self, entity, http_session, db_session, df_record):
        saved = await df_to_db(region=self.region,
                               provider=self.provider,
                               data_schema=self.data_schema,
                               db_session=db_session,
                               df=df_record)
        return True, saved

    @time_it
    async def on_finish_entity(self, entity, http_session, db_session, result):
        pass

    async def on_finish(self, entities):
        pass
