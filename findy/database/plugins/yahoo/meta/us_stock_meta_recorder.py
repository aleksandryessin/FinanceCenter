# -*- coding: utf-8 -*-
from yfinance import Ticker

from findy.interface import Region, Provider, EntityType
from findy.database.schema.meta.stock_meta import StockDetail
from findy.database.recorder import RecorderForEntities
from findy.database.quote import get_entities
from findy.utils.functool import time_it


class YahooUsStockDetailRecorder(RecorderForEntities):
    region = Region.US
    provider = Provider.Yahoo
    data_schema = StockDetail

    def __init__(self, batch_size=10, force_update=False, sleep_time=5, codes=None, share_para=None) -> None:
        super().__init__(entity_type=EntityType.StockDetail, batch_size=batch_size, force_update=force_update, sleep_time=sleep_time, codes=codes, share_para=share_para)

    async def init_entities(self, db_session):
        entities, column_names = get_entities(
            region=self.region,
            provider=self.provider,
            db_session=db_session,
            entity_type=EntityType.StockDetail,
            codes=self.codes,
            filters=[
                StockDetail.market_cap == 0,
                StockDetail.sector.is_(None),
                StockDetail.country.is_(None)
            ])
        return entities

    def yh_get_info(self, code):
        retry = 3
        error_msg = None

        for _ in range(retry):
            try:
                return Ticker(code).info
            except Exception as e:
                msg = str(e)
                error_msg = f'yh_get_info, code: {code}, error: {msg}'
                # time.sleep(60 * 10)

        self.logger.error(error_msg)
        return None

    @time_it
    async def eval(self, entity, http_session, db_session):
        return not isinstance(entity, StockDetail), None

    @time_it
    async def record(self, entity, http_session, db_session, para):
        # get stock info
        info = self.yh_get_info(entity.code)

        if info is None or len(info) == 0:
            return True, None

        if not entity.sector:
            entity.sector = info.get('sector', None)

        if not entity.industry:
            entity.industry = info.get('industry', None)

        if not entity.market_cap or entity.market_cap == 0:
            entity.market_cap = info.get('market_cap', 0)

        entity.profile = info.get('longBusinessSummary', None)
        entity.state = info.get('state', None)
        entity.city = info.get('city', None)
        entity.zip_code = info.get('zip', None)

        entity.last_sale = info.get('previousClose', None)

        return False, None

    @time_it
    async def persist(self, entity, http_session, db_session, df_record):
        try:
            db_session.commit()
        except Exception as e:
            self.logger.error(f'{self.__class__.__name__}, rollback error: {e}')
            db_session.rollback()
        finally:
            db_session.close()
        return True, 1

    @time_it
    async def on_finish_entity(self, entity, http_session, db_session, result):
        pass

    async def on_finish(self, entities):
        pass
