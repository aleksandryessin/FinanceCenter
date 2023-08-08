# -*- coding: utf-8 -*-
import pandas as pd

from findy.interface import Region, Provider, ChnExchange, EntityType
from findy.database.schema import IntervalLevel, AdjustType
from findy.database.schema.meta.stock_meta import Stock
from findy.database.schema.datatype import StockKdataCommon
from findy.database.recorder import KDataRecorder
from findy.database.plugins.baostock.common import (to_bao_trading_level, to_bao_entity_id,
                                                    to_bao_trading_field, to_bao_adjust_flag)
from findy.database.quote import get_entities
from findy.utils.functool import time_it
from findy.utils.pd import pd_valid
from findy.utils.time import PD_TIME_FORMAT_DAY, PD_TIME_FORMAT_ISO8601, to_time_str

import findy.vendor.baostock as bs
try:
    bs.login()
except:
    pass


class BaoChinaStockKdataRecorder(KDataRecorder):
    region = Region.CHN
    provider = Provider.BaoStock
    entity_schema = Stock
    # 只是为了把recorder注册到data_schema
    data_schema = StockKdataCommon
    exchanges = [e.value for e in ChnExchange]

    def __init__(self,
                 entity_ids=None,
                 codes=None,
                 batch_size=10,
                 force_update=True,
                 sleep_time=0,
                 fix_duplicate_way='ignore',
                 start_timestamp=None,
                 end_timestamp=None,
                 level=IntervalLevel.LEVEL_1WEEK,
                 adjust_type=AdjustType.qfq,
                 share_para=None) -> None:
        level = IntervalLevel(level)
        adjust_type = AdjustType(adjust_type)
        self.data_schema = self.get_kdata_schema(entity_type=EntityType.Stock, level=level, adjust_type=adjust_type)
        self.bao_trading_level = to_bao_trading_level(level)

        super().__init__(EntityType.Stock, entity_ids, codes, batch_size, force_update, sleep_time,
                         fix_duplicate_way, start_timestamp, end_timestamp, level,
                         share_para=share_para)
        self.adjust_type = adjust_type

    async def init_entities(self, db_session):
        # init the entity list
        entities, column_names = get_entities(
            region=self.region,
            provider=self.provider,
            db_session=db_session,
            entity_schema=self.entity_schema,
            entity_type=self.entity_type,
            exchanges=self.exchanges,
            entity_ids=self.entity_ids,
            codes=self.codes,
            filters=[Stock.is_active.is_(True)])
        return entities

    def generate_domain_id(self, entity, df, time_fmt=PD_TIME_FORMAT_DAY):
        format = PD_TIME_FORMAT_DAY if self.level >= IntervalLevel.LEVEL_1DAY else PD_TIME_FORMAT_ISO8601
        return df['entity_id'] + '_' + df[self.get_evaluated_time_field()].dt.strftime(format)

    def bao_get_bars(self, code, start, end, frequency="d", adjustflag="3",
                     fields="date, code, open, high, low, close, preclose, volume, amount, adjustflag, turn, tradestatus, pctChg, isST"):

        def _bao_get_bars(code, start, end, frequency, adjustflag, fields):
            k_rs = bs.query_history_k_data_plus(code, start_date=start, end_date=end, frequency=frequency,
                                                adjustflag=adjustflag, fields=fields)
            return k_rs.get_data()

        self.logger.debug("HTTP GET: bars, with code={}, unit={}, start={}, end={}".format(code, frequency, start, end))
        try:
            return _bao_get_bars(code, start, end, frequency, adjustflag, fields)
        except Exception as e:
            self.logger.error(f'bao_get_bars, frequency: {frequency}, code: {code}, error: {e}')
        return None

    @time_it
    async def record(self, entity, http_session, db_session, para):
        (start, end, size, timestamps) = para

        start = to_time_str(start)
        if self.bao_trading_level in ['d', 'w', 'm']:
            start = max(start, "1990-12-19")
        else:
            start = max(start, "1999-07-26")

        df = self.bao_get_bars(to_bao_entity_id(entity),
                               start=start,
                               end=end if end is None else to_time_str(end),
                               frequency=self.bao_trading_level,
                               fields=to_bao_trading_field(self.bao_trading_level),
                               adjustflag=to_bao_adjust_flag(self.adjust_type))
        # await asyncio.sleep(0.005)

        if pd_valid(df):
            return False, self.format(entity, df)

        return True, None

    def format(self, entity, df):
        if self.bao_trading_level == 'd':
            df.rename(columns={'turn': 'turnover', 'date': 'timestamp', 'preclose': 'pre_close', 'pctChg': 'change_pct',
                               'peTTM': 'pe_ttm', 'psTTM': 'ps_ttm', 'pcfNcfTTM': 'pcf_ncf_ttm', 'pbMRQ': 'pb_mrq', 'isST': 'is_st'}, inplace=True)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['is_st'] = df['is_st'].apply(lambda x: 1 if x == '1' else 0)

        elif self.bao_trading_level == 'w' or self.bao_trading_level == 'm':
            df.rename(columns={'turn': 'turnover', 'date': 'timestamp', 'pctChg': 'change_pct'}, inplace=True)
            df['timestamp'] = pd.to_datetime(df['timestamp'])

        else:
            df.rename(columns={'time': 'timestamp'}, inplace=True)
            df['timestamp'] = pd.to_datetime(df['timestamp'], format='%Y%m%d%H%M%S%f')

        cols = df.select_dtypes('object').columns.to_list()
        cols.remove('adjustflag')
        df.replace(r'^\s*$', 0.0, regex=True, inplace=True)
        df[cols] = df[cols].astype(float)

        df['entity_id'] = entity.id
        df['provider'] = self.provider.value
        df['name'] = entity.name
        df['code'] = entity.code
        df['level'] = self.level.value
        df.replace({'adjustflag': {'1': 'hfq', '2': 'qfq', '3': 'normal'}}, inplace=True)

        df['id'] = self.generate_domain_id(entity, df)
        return df

    @time_it
    async def on_finish_entity(self, entity, http_session, db_session, result):
        if result == 2 and not entity.is_active:
            try:
                db_session.commit()
            except Exception as e:
                self.logger.error(f'{self.__class__.__name__}, error: {e}')
                db_session.rollback()
            finally:
                db_session.close()

    async def on_finish(self, entities):
        pass
