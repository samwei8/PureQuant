# -*- coding:utf-8 -*-

"""
交易模块

Author: Gary-Hertel
Date:   2020/07/09
email: interstella.ranger2020@gmail.com
"""
import time
from purequant.exchange.okex import spot_api as okexspot
from purequant.exchange.okex import futures_api as okexfutures
from purequant.exchange.okex import swap_api as okexswap
from purequant.exchange.huobi import huobi_futures as huobifutures
from purequant.exchange.huobi import huobi_swap as huobiswap
from purequant.exchange.binance import binance_spot
from purequant.exchange.binance import binance_futures
from purequant.exchange.binance import binance_swap
from purequant.exchange.bitmex.bitmex import Bitmex
from purequant.time import ts_to_utc_str
from purequant.exchange.huobi import huobi_spot as huobispot
from purequant.config import config
from purequant.exceptions import *
from purequant.storage import storage

class OKEXFUTURES:
    """okex交割合约操作  https://www.okex.com/docs/zh/#futures-README"""
    def __init__(self, access_key, secret_key, passphrase, instrument_id, leverage=None):
        """
        okex交割合约，初始化时会自动设置成全仓模式，可以传入参数设定开仓杠杆倍数。
        设置合约币种账户模式时，注意：当前有仓位或者有挂单时禁止切换账户模式。
        :param access_key:
        :param secret_key:
        :param passphrase:
        :param instrument_id: 例如："BTC-USD-201225", "BTC-USDT-201225"
        :param leverage:杠杆倍数，如不填则默认设置为20倍杠杆
        """
        self.__access_key = access_key
        self.__secret_key = secret_key
        self.__passphrase = passphrase
        self.__instrument_id = instrument_id
        self.__okex_futures = okexfutures.FutureAPI(self.__access_key, self.__secret_key, self.__passphrase)
        self.__leverage = leverage or 20
        try:
            self.__okex_futures.set_margin_mode(underlying=self.__instrument_id.split("-")[0] + "-" + self.__instrument_id.split("-")[1],
                                                margin_mode="crossed")
            self.__okex_futures.set_leverage(leverage=self.__leverage,
                                             underlying=self.__instrument_id.split("-")[0] + "-" +
                                                        self.__instrument_id.split("-")[1])  # 设置账户模式为全仓模式后再设置杠杆倍数
        except Exception as e:
            print("OKEX交割合约设置全仓模式失败！错误：{}".format(str(e)))

    def get_single_equity(self, symbol):
        """
        获取单个合约账户的权益
        :param symbol: 例如"btc-usdt"
        :return:返回浮点数
        """
        data = self.__okex_futures.get_coin_account(underlying=symbol)
        result =float(data["equity"])
        return result

    def buy(self, price, size, order_type=None):
        if config.backtest != "enabled":   # 实盘模式
            order_type = order_type or 0    # 如果不填order_type,则默认为普通委托
            result = self.__okex_futures.take_order(self.__instrument_id, 1, price, size, order_type=order_type) # 下订单
            order_info = self.get_order_info(order_id=result['order_id'])   # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ": # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true": # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:    # 如果撤单失败，则订单可能在此期间已完全成交或部分成交
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功": # 已完全成交时，以原下单数量重发；部分成交时，重发委托数量为原下单数量减去已成交数量
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:     # 撤单失败时，说明订单已完全成交
                            order_info = self.get_order_info(order_id=result['order_id'])   # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:     # 撤单失败时，说明订单已完全成交，再查询一次订单状态，如果已完全成交，返回下单结果
                            order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true": # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['order_id'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['order_id'])
                    state = self.get_order_info(order_id=result['order_id'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                    if order_info["订单状态"] == "完全成交":
                        return {"【交易提醒】下单结果": order_info}
            else:   # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:   # 回测模式
            return "回测模拟下单成功！"

    def sell(self, price, size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            order_type = order_type or 0
            result = self.__okex_futures.take_order(self.__instrument_id, 3, price, size, order_type=order_type)
            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['order_id'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['order_id'])
                    state = self.get_order_info(order_id=result['order_id'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                    if order_info["订单状态"] == "完全成交":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:   # 回测模式
            return "回测模拟下单成功！"

    def sellshort(self, price, size, order_type=None):
        if config.backtest != "enabled":   # 实盘模式
            order_type = order_type or 0
            result = self.__okex_futures.take_order(self.__instrument_id, 2, price, size, order_type=order_type)
            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['order_id'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['order_id'])
                    state = self.get_order_info(order_id=result['order_id'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                    if order_info["订单状态"] == "完全成交":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:   # 回测模式
            return "回测模拟下单成功！"

    def buytocover(self, price, size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            order_type = order_type or 0
            result = self.__okex_futures.take_order(self.__instrument_id, 4, price, size, order_type=order_type)
            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['order_id'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['order_id'])
                    state = self.get_order_info(order_id=result['order_id'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['order_id'])  # 再查询一次订单状态
                    if order_info["订单状态"] == "完全成交":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:   # 回测模式
            return "回测模拟下单成功！"

    def BUY(self, cover_short_price, cover_short_size, open_long_price, open_long_size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            order_type = order_type or 0
            result1 = self.buytocover(cover_short_price, cover_short_size, order_type)
            if "完全成交" in str(result1):
                result2 = self.buy(open_long_price, open_long_size, order_type)
                return {"平仓结果": result1, "开仓结果": result2}
            else:
                return result1
        else:   # 回测模式
            return "回测模拟下单成功！"

    def SELL(self, cover_long_price, cover_long_size, open_short_price, open_short_size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            order_type = order_type or 0
            result1 = self.sell(cover_long_price, cover_long_size, order_type)
            if "完全成交" in str(result1):
                result2 = self.sellshort(open_short_price, open_short_size, order_type)
                return {"平仓结果": result1, "开仓结果": result2}
            else:
                return result1
        else:   # 回测模式
            return "回测模拟下单成功！"

    def get_order_list(self, state, limit):
        receipt = self.__okex_futures.get_order_list(self.__instrument_id, state=state, limit=limit)
        return receipt

    def revoke_order(self, order_id):
        receipt = self.__okex_futures.revoke_order(self.__instrument_id, order_id)
        if receipt['error_code'] == "0":
            return '【交易提醒】撤单成功'
        else:
            return '【交易提醒】撤单失败' + receipt['error_message']

    def get_order_info(self, order_id):
        result = self.__okex_futures.get_order_info(self.__instrument_id, order_id)
        instrument_id = result['instrument_id']
        action = None
        if result['type'] == '1':
            action = "买入开多"
        elif result['type'] == '2':
            action = "卖出开空"
        if result['type'] == '3':
            action = "卖出平多"
        if result['type'] == '4':
            action = "买入平空"
        # 根据返回的数据中的合约id来判断是u本位合约还是币本位合约，计算成交金额两种方式有区别
        price = float(result['price_avg'])   # 成交均价
        amount = int(result['filled_qty'])   # 已成交数量
        if instrument_id.split("-")[1] == "usd" or instrument_id.split("-")[1] == "USD":
            turnover = float(result['contract_val']) * int(result['filled_qty'])
        elif instrument_id.split("-")[1] == "usdt" or instrument_id.split("-")[1] == "USDT":
            turnover = round(float(result['contract_val']) * int(result['filled_qty']) * float(result['price_avg']), 2)

        if int(result['state']) == 2:
            dict = {"交易所": "Okex交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "完全成交", "成交均价": price,
                    "已成交数量": amount, "成交金额": turnover}
            return dict
        elif int(result['state']) == -2:
            dict = {"交易所": "Okex交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "失败"}
            return dict
        elif int(result['state']) == -1:
            dict = {"交易所": "Okex交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "撤单成功", "成交均价": price,
                    "已成交数量": amount, "成交金额": turnover}
            return dict
        elif int(result['state']) == 0:
            dict = {"交易所": "Okex交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "等待成交"}
            return dict
        elif int(result['state']) == 1:
            dict = {"交易所": "Okex交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "部分成交", "成交均价": price,
                    "已成交数量": amount, "成交金额": turnover}
            return dict
        elif int(result['state']) == 3:
            dict = {"交易所": "Okex交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "下单中"}
            return dict
        elif int(result['state']) == 4:
            dict = {"交易所": "Okex交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "撤单中"}
            return dict

    def get_kline(self, time_frame):
        if time_frame == "1m" or time_frame == "1M":
            granularity = '60'
        elif time_frame == '3m' or time_frame == "3M":
            granularity = '180'
        elif time_frame == '5m' or time_frame == "5M":
            granularity = '300'
        elif time_frame == '15m' or time_frame == "15M":
            granularity = '900'
        elif time_frame == '30m' or time_frame == "30M":
            granularity = '1800'
        elif time_frame == '1h' or time_frame == "1H":
            granularity = '3600'
        elif time_frame == '2h' or time_frame == "2H":
            granularity = '7200'
        elif time_frame == '4h' or time_frame == "4H":
            granularity = '14400'
        elif time_frame == '6h' or time_frame == "6H":
            granularity = '21600'
        elif time_frame == '12h' or time_frame == "12H":
            granularity = '43200'
        elif time_frame == '1d' or time_frame == "1D":
            granularity = '86400'
        else:
            raise KlineError
        receipt = self.__okex_futures.get_kline(self.__instrument_id, granularity=granularity)
        return receipt

    def get_position(self, mode=None):
        result = self.__okex_futures.get_specific_position(instrument_id=self.__instrument_id)
        if mode == "both":     # 若传入参数为"both"则查询双向持仓模式的持仓信息
            dict = {"long":
                {
                'amount': int(result['holding'][0]['long_qty']),
                'price': float(result['holding'][0]['long_avg_cost'])
            },
            "short":
                {
                'amount': int(result['holding'][0]['short_qty']),
                'price': float(result['holding'][0]['short_avg_cost'])
            }
            }
            return dict
        else:   # 未传入参数则默认为查询单向持仓模式的持仓信息
            if int(result['holding'][0]['long_qty']) > 0:
                dict = {'direction': 'long', 'amount': int(result['holding'][0]['long_qty']),
                        'price': float(result['holding'][0]['long_avg_cost'])}
                return dict
            elif int(result['holding'][0]['short_qty']) > 0:
                dict = {'direction': 'short', 'amount': int(result['holding'][0]['short_qty']),
                        'price': float(result['holding'][0]['short_avg_cost'])}
                return dict
            else:
                dict = {'direction': 'none', 'amount': 0, 'price': 0.0}
                return dict

    def get_ticker(self):
        receipt = self.__okex_futures.get_specific_ticker(instrument_id=self.__instrument_id)
        return receipt

    def get_contract_value(self):
        receipt = self.__okex_futures.get_products()
        result = {}
        for item in receipt:
            result[item['instrument_id']] = item['contract_val']
        contract_value = float(result[self.__instrument_id])
        return contract_value

    def get_depth(self, type=None, size=None):
        """
        OKEX交割合约获取深度数据
        :param type: 如不传参，返回asks和bids；只获取asks传入type="asks"；只获取"bids"传入type="bids"
        :param size: 返回深度档位数量，最多返回200，默认10档
        :return:
        """
        size = size or 10
        response = self.__okex_futures.get_depth(self.__instrument_id, size=size)
        asks_list = response["asks"]
        bids_list = response["bids"]
        asks= []
        bids = []
        for i in asks_list:
            asks.append(float(i[0]))
        for j in bids_list:
            bids.append(float(j[0]))
        if type == "asks":
            return asks
        elif type == "bids":
            return bids
        else:
            return response

class OKEXSPOT:
    """okex现货操作  https://www.okex.com/docs/zh/#spot-README"""
    def __init__(self, access_key, secret_key, passphrase, instrument_id):
        """
        okex现货
        :param access_key:
        :param secret_key:
        :param passphrase:
        :param instrument_id:例如："ETC-USDT"
        """
        self.__access_key = access_key
        self.__secret_key = secret_key
        self.__passphrase = passphrase
        self.__instrument_id = instrument_id
        self.__okex_spot = okexspot.SpotAPI(self.__access_key, self.__secret_key, self.__passphrase)

    def buy(self, price, size, order_type=None, type=None, notional=""):
        """
        okex现货买入
        :param price:价格
        :param size:数量
        :param order_type:参数填数字
        0：普通委托（order type不填或填0都是普通委托）
        1：只做Maker（Post only）
        2：全部成交或立即取消（FOK）
        3：立即成交并取消剩余（IOC）
        :param type:limit或market（默认是limit）。当以market（市价）下单，order_type只能选择0（普通委托）
        :param notional:买入金额，市价买入时必填notional
        :return:
        """
        if config.backtest != "enabled":    # 实盘模式
            order_type = order_type or 0
            type = type or "limit"
            result = self.__okex_spot.take_order(instrument_id=self.__instrument_id, side="buy", type=type, size=size, price=price, order_type=order_type, notional=notional)
            try:
                order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
            except:
                raise SendOrderError(result['error_message'])
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except: # 如撤单失败，则说明已经完全成交，此时再查询一次订单状态然后返回下单结果
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":    # 部分成交时撤单然后重发委托，下单数量为原下单数量减去已成交数量
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except: # 如撤单失败，则说明已经完全成交，此时再查询一次订单状态然后返回下单结果
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['order_id'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:  # 如撤单失败，则说明已经完全成交，此时再查询一次订单状态然后返回下单结果
                        order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":    # 部分成交时撤单然后重发委托，下单数量为原下单数量减去已成交数量
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except: # 如撤单失败，则说明已经完全成交，此时再查询一次订单状态然后返回下单结果
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['order_id'])
                    state = self.get_order_info(order_id=result['order_id'])
                    return {"【交易提醒】下单结果": state}
                except:  # 如撤单失败，则说明已经完全成交，此时再查询一次订单状态然后返回下单结果
                    order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:   # 回测模式
            return "回测模拟下单成功！"

    def sell(self, price, size, order_type=None, type=None):
        """
        okex现货卖出
        :param price: 价格
        :param size:卖出数量，市价卖出时必填size
        :param order_type:参数填数字
        0：普通委托（order type不填或填0都是普通委托）
        1：只做Maker（Post only）
        2：全部成交或立即取消（FOK）
        3：立即成交并取消剩余（IOC）
        :param type:limit或market（默认是limit）。当以market（市价）下单，order_type只能选择0（普通委托）
        :return:
        """
        if config.backtest != "enabled":    # 实盘模式
            order_type = order_type or 0
            type = type or "limit"
            result = self.__okex_spot.take_order(instrument_id=self.__instrument_id, side="sell", type=type, size=size, price=price, order_type=order_type)
            try:
                order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
            except:
                raise SendOrderError(result['error_message'])
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except: # 如撤单失败，则说明已经完全成交，此时再查询一次订单状态然后返回下单结果
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":    # 部分成交时撤单然后重发委托，下单数量为原下单数量减去已成交数量
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except: # 如撤单失败，则说明已经完全成交，此时再查询一次订单状态然后返回下单结果
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['order_id'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:  # 如撤单失败，则说明已经完全成交，此时再查询一次订单状态然后返回下单结果
                        order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":    # 部分成交时撤单然后重发委托，下单数量为原下单数量减去已成交数量
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except: # 如撤单失败，则说明已经完全成交，此时再查询一次订单状态然后返回下单结果
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['order_id'])
                    state = self.get_order_info(order_id=result['order_id'])
                    return {"【交易提醒】下单结果": state}
                except:  # 如撤单失败，则说明已经完全成交，此时再查询一次订单状态然后返回下单结果
                    order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:   # 回测模式
            return "回测模拟下单成功！"

    def get_order_list(self, state, limit):
        receipt = self.__okex_spot.get_orders_list(self.__instrument_id, state=state, limit=limit)
        return receipt

    def revoke_order(self, order_id):
        receipt = self.__okex_spot.revoke_order(self.__instrument_id, order_id)
        if receipt['error_code'] == "0":
            return '【交易提醒】撤单成功'
        else:
            return '【交易提醒】撤单失败' + receipt['error_message']

    def get_order_info(self, order_id):
        result = self.__okex_spot.get_order_info(self.__instrument_id, order_id)
        instrument_id = result['instrument_id']
        action = None
        if result['side'] == 'buy':
            action = "买入开多"
        if result['side'] == 'sell':
            action = "卖出平多"
        if int(result['state']) == 2:
            dict = {"交易所": "Okex现货", "合约ID": instrument_id, "方向": action, "订单状态": "完全成交", "成交均价": float(result['price_avg']),
                    "已成交数量": float(result['filled_size']), "成交金额": float(result['filled_notional'])}
            return dict
        elif int(result['state']) == -2:
            dict = {"交易所": "Okex现货", "合约ID": instrument_id, "方向": action, "订单状态": "失败"}
            return dict
        elif int(result['state']) == -1:
            dict = {"交易所": "Okex现货", "合约ID": instrument_id, "方向": action, "订单状态": "撤单成功", "成交均价": float(result['price_avg']),
                    "已成交数量": float(result['filled_size']), "成交金额": float(result['filled_notional'])}
            return dict
        elif int(result['state']) == 0:
            dict = {"交易所": "Okex现货", "合约ID": instrument_id, "方向": action, "订单状态": "等待成交"}
            return dict
        elif int(result['state']) == 1:
            dict = {"交易所": "Okex现货", "合约ID": instrument_id, "方向": action, "订单状态": "部分成交", "成交均价": float(result['price_avg']),
                    "已成交数量": float(result['filled_size']), "成交金额": float(result['filled_notional'])}
            return dict
        elif int(result['state']) == 3:
            dict = {"交易所": "Okex现货", "合约ID": instrument_id, "方向": action, "订单状态": "下单中"}
            return dict
        elif int(result['state']) == 4:
            dict = {"交易所": "Okex现货", "合约ID": instrument_id, "方向": action, "订单状态": "撤单中"}
            return dict

    def get_kline(self, time_frame):
        if time_frame == "1m" or time_frame == "1M":
            granularity = '60'
        elif time_frame == '3m' or time_frame == "3M":
            granularity = '180'
        elif time_frame == '5m' or time_frame == "5M":
            granularity = '300'
        elif time_frame == '15m' or time_frame == "15M":
            granularity = '900'
        elif time_frame == '30m' or time_frame == "30M":
            granularity = '1800'
        elif time_frame == '1h' or time_frame == "1H":
            granularity = '3600'
        elif time_frame == '2h' or time_frame == "2H":
            granularity = '7200'
        elif time_frame == '4h' or time_frame == "4H":
            granularity = '14400'
        elif time_frame == '6h' or time_frame == "6H":
            granularity = '21600'
        elif time_frame == '12h' or time_frame == "12H":
            granularity = '43200'
        elif time_frame == '1d' or time_frame == "1D":
            granularity = '86400'
        else:
            raise KlineError
        receipt = self.__okex_spot.get_kline(self.__instrument_id, granularity=granularity)
        return receipt

    def get_position(self):
        """OKEX现货，如交易对为'ETC-USDT', 则获取的是ETC的可用余额"""
        currency = self.__instrument_id.split('-')[0]
        receipt = self.__okex_spot.get_coin_account_info(currency=currency)
        direction = 'long'
        amount = float(receipt['balance'])
        price = None
        result = {'direction': direction, 'amount': amount, 'price': price}
        return result

    def get_ticker(self):
        receipt = self.__okex_spot.get_specific_ticker(instrument_id=self.__instrument_id)
        return receipt

    def get_depth(self, type=None, size=None):
        """
        OKEX现货获取深度数据
        :param type: 如不传参，返回asks和bids；只获取asks传入type="asks"；只获取"bids"传入type="bids"
        :param size: 返回深度档位数量，最多返回200，默认10档
        :return:
        """
        size = size or 10
        response = self.__okex_spot.get_depth(self.__instrument_id, size=size)
        asks_list = response['asks']
        bids_list = response['bids']
        bids = []
        asks = []
        for i in asks_list:
            asks.append(float(i[0]))
        for j in bids_list:
            bids.append(float(j[0]))
        if type == "asks":
            return asks
        elif type == "bids":
            return bids
        else:
            return response

    def get_single_equity(self, currency):
        """
        获取币币账户单个币种的余额、冻结和可用等信息。
        :param currency: 例如"btc"
        :return:返回浮点数
        """
        data = self.__okex_spot.get_coin_account_info(currency=currency)
        result =float(data["balance"])
        return result

class OKEXSWAP:
    """okex永续合约操作 https://www.okex.com/docs/zh/#swap-README"""
    def __init__(self, access_key, secret_key, passphrase, instrument_id, leverage=None):
        """
        okex永续合约
        :param access_key:
        :param secret_key:
        :param passphrase:
        :param instrument_id: 例如："BTC-USDT-SWAP", "BTC-USD-SWAP"
        :param leverage:杠杆倍数，如不填则默认设置20倍杠杆
        """
        self.__access_key = access_key
        self.__secret_key = secret_key
        self.__passphrase = passphrase
        self.__instrument_id = instrument_id
        self.__okex_swap = okexswap.SwapAPI(self.__access_key, self.__secret_key, self.__passphrase)
        self.__leverage = leverage or 20
        try:
            self.__okex_swap.set_leverage(leverage=self.__leverage, instrument_id=self.__instrument_id, side=3)
        except Exception as e:
            print("OKEX永续合约设置杠杆倍数失败！请检查账户是否已设置成全仓模式！错误：{}".format(str(e)))

    def get_single_equity(self, instrument_id):
        """
        获取单个合约账户的权益
        :param instrument_id: 例如"TRX-USDT-SWAP"
        :return:返回浮点数
        """
        data = self.__okex_swap.get_coin_account(instrument_id=instrument_id)
        result =float(data["info"]["equity"])
        return result

    def buy(self, price, size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            order_type = order_type or 0  # 如果不填order_type,则默认为普通委托
            try:
                result = self.__okex_swap.take_order(self.__instrument_id, 1, price, size, order_type=order_type)
            except Exception as e:
                raise SendOrderError(e)
            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['order_id'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['order_id'])
                    state = self.get_order_info(order_id=result['order_id'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:   # 回测模式
            return "回测模拟下单成功！"

    def sell(self, price, size, order_type=None):
        if config.backtest != "enabled":
            order_type = order_type or 0
            try:
                result = self.__okex_swap.take_order(self.__instrument_id, 3, price, size, order_type=order_type)
            except Exception as e:
                raise SendOrderError(e)
            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['order_id'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['order_id'])
                    state = self.get_order_info(order_id=result['order_id'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:   # 回测模式
            return "回测模拟下单成功！"

    def sellshort(self, price, size, order_type=None):
        if config.backtest != "enabled":
            order_type = order_type or 0
            try:
                result = self.__okex_swap.take_order(self.__instrument_id, 2, price, size, order_type=order_type)
            except Exception as e:
                raise SendOrderError(e)
            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['order_id'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['order_id'])
                    state = self.get_order_info(order_id=result['order_id'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:   # 回测模式
            return "回测模拟下单成功！"

    def buytocover(self, price, size, order_type=None):
        if config.backtest != "enabled":
            order_type = order_type or 0
            try:
                result = self.__okex_swap.take_order(self.__instrument_id, 4, price, size, order_type=order_type)
            except Exception as e:
                raise SendOrderError(e)
            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['order_id'])
                            state = self.get_order_info(order_id=result['order_id'])
                            if state['订单状态'] == "撤单成功":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['order_id'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['order_id'])
                        state = self.get_order_info(order_id=result['order_id'])
                        if state['订单状态'] == "撤单成功":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['order_id'])
                    state = self.get_order_info(order_id=result['order_id'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['order_id'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:   # 回测模式
            return "回测模拟下单成功！"

    def BUY(self, cover_short_price, cover_short_size, open_long_price, open_long_size, order_type=None):
        if config.backtest != "enabled":
            order_type = order_type or 0
            result1 = self.buytocover(cover_short_price, cover_short_size, order_type)
            if "完全成交" in str(result1):
                result2 = self.buy(open_long_price, open_long_size, order_type)
                return {"平仓结果": result1, "开仓结果": result2}
            else:
                return result1
        else:   # 回测模式
            return "回测模拟下单成功！"

    def SELL(self, cover_long_price, cover_long_size, open_short_price, open_short_size, order_type=None):
        if config.backtest != "enabled":
            order_type = order_type or 0
            result1 = self.sell(cover_long_price, cover_long_size, order_type)
            if "完全成交" in str(result1):
                result2 = self.sellshort(open_short_price, open_short_size, order_type)
                return {"平仓结果": result1, "开仓结果": result2}
            else:
                return result1
        else:  # 回测模式
            return "回测模拟下单成功！"

    def get_order_list(self, state, limit):
        receipt = self.__okex_swap.get_order_list(self.__instrument_id, state=state, limit=limit)
        return receipt

    def revoke_order(self, order_id):
        receipt = self.__okex_swap.revoke_order(self.__instrument_id, order_id)
        if receipt['error_code'] == "0":
            return '【交易提醒】撤单成功'
        else:
            return '【交易提醒】撤单失败' + receipt['error_message']

    def get_order_info(self, order_id):
        result = self.__okex_swap.get_order_info(self.__instrument_id, order_id)
        instrument_id = result['instrument_id']
        action = None
        if result['type'] == '1':
            action = "买入开多"
        elif result['type'] == '2':
            action = "卖出开空"
        if result['type'] == '3':
            action = "卖出平多"
        if result['type'] == '4':
            action = "买入平空"

        price = float(result['price_avg'])  # 成交均价
        amount = int(result['filled_qty'])  # 已成交数量
        if instrument_id.split("-")[1] == "usd" or instrument_id.split("-")[1] == "USD":
            turnover = float(result['contract_val']) * int(result['filled_qty'])
        elif instrument_id.split("-")[1] == "usdt" or instrument_id.split("-")[1] == "USDT":
            turnover = round(float(result['contract_val']) * int(result['filled_qty']) * float(result['price_avg']), 2)
        
        if int(result['state']) == 2:
            dict = {"交易所": "Okex永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "完全成交", "成交均价": price,
                    "已成交数量": amount, "成交金额": turnover}
            return dict
        elif int(result['state']) == -2:
            dict = {"交易所": "Okex永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "失败"}
            return dict
        elif int(result['state']) == -1:
            dict = {"交易所": "Okex永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "撤单成功", "成交均价": price,
                    "已成交数量": amount, "成交金额": turnover}
            return dict
        elif int(result['state']) == 0:
            dict = {"交易所": "Okex永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "等待成交"}
            return dict
        elif int(result['state']) == 1:
            dict = {"交易所": "Okex永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "部分成交", "成交均价": price,
                    "已成交数量": amount, "成交金额": turnover}
            return dict
        elif int(result['state']) == 3:
            dict = {"交易所": "Okex永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "下单中"}
            return dict
        elif int(result['state']) == 4:
            dict = {"交易所": "Okex永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "撤单中"}
            return dict

    def get_kline(self, time_frame):
        if time_frame == "1m" or time_frame == "1M":
            granularity = '60'
        elif time_frame == '3m' or time_frame == "3M":
            granularity = '180'
        elif time_frame == '5m' or time_frame == "5M":
            granularity = '300'
        elif time_frame == '15m' or time_frame == "15M":
            granularity = '900'
        elif time_frame == '30m' or time_frame == "30M":
            granularity = '1800'
        elif time_frame == '1h' or time_frame == "1H":
            granularity = '3600'
        elif time_frame == '2h' or time_frame == "2H":
            granularity = '7200'
        elif time_frame == '4h' or time_frame == "4H":
            granularity = '14400'
        elif time_frame == '6h' or time_frame == "6H":
            granularity = '21600'
        elif time_frame == '12h' or time_frame == "12H":
            granularity = '43200'
        elif time_frame == '1d' or time_frame == "1D":
            granularity = '86400'
        else:
            raise KlineError
        receipt = self.__okex_swap.get_kline(self.__instrument_id, granularity=granularity)
        return receipt

    def get_position(self, mode=None):
        receipt = self.__okex_swap.get_specific_position(self.__instrument_id)
        if mode == "both":
            result = {
                receipt['holding'][0]["side"]: {
                    "price": float(receipt['holding'][0]['avg_cost']),
                    "amount": int(receipt['holding'][0]['position'])
                },
                receipt['holding'][1]["side"]: {
                    "price": float(receipt['holding'][1]['avg_cost']),
                    "amount": int(receipt['holding'][1]['position'])
                }
            }
            return result
        else:
            direction = receipt['holding'][0]['side']
            amount = int(receipt['holding'][0]['position'])
            price = float(receipt['holding'][0]['avg_cost'])
            if amount == 0:
                direction = "none"
            result = {'direction': direction, 'amount': amount, 'price': price}
            return result

    def get_contract_value(self):
        receipt = self.__okex_swap.get_instruments()
        result = {}
        for item in receipt:
            result[item['instrument_id']]=item['contract_val']
        contract_value = float(result[self.__instrument_id])
        return contract_value

    def get_ticker(self):
        receipt = self.__okex_swap.get_specific_ticker(instrument_id=self.__instrument_id)
        return receipt

    def get_depth(self, type=None, size=None):
        """
        OKEX永续合约获取深度数据
        :param type: 如不传参，返回asks和bids；只获取asks传入type="asks"；只获取"bids"传入type="bids"
        :param size: 返回深度档位数量，最多返回200，默认10档
        :return:
        """
        size = size or 10
        response = self.__okex_swap.get_depth(self.__instrument_id, size=size)
        asks_list = response["asks"]
        bids_list = response["bids"]
        asks= []
        bids = []
        for i in asks_list:
            asks.append(float(i[0]))
        for j in bids_list:
            bids.append(float(j[0]))
        if type == "asks":
            return asks
        elif type == "bids":
            return bids
        else:
            return response

class HUOBIFUTURES:
    """火币合约 https://huobiapi.github.io/docs/dm/v1/cn/#5ea2e0cde2"""
    def __init__(self, access_key, secret_key, instrument_id, contract_type=None, leverage=None):
        """
        :param access_key:
        :param secret_key:
        :param instrument_id: 'BTC-USD-201225'
        :param contract_type:如不传入此参数，则默认只能交易季度或次季合约
        :param leverage:杠杆倍速，如不填则默认设置为20倍杠杆
        """
        self.__access_key = access_key
        self.__secret_key = secret_key
        self.__instrument_id = instrument_id
        self.__huobi_futures = huobifutures.HuobiFutures(self.__access_key, self.__secret_key)
        self.__symbol = self.__instrument_id.split("-")[0]
        self.__contract_code = self.__instrument_id.split("-")[0] + self.__instrument_id.split("-")[2]
        self.__leverage = leverage or 20

        if contract_type is not None:
            self.__contract_type = contract_type
        else:
            if self.__instrument_id.split("-")[2][2:4] == '03' or self.__instrument_id.split("-")[2][2:4] == '09':
                self.__contract_type = "quarter"
            elif self.__instrument_id.split("-")[2][2:4] == '06' or self.__instrument_id.split("-")[2][2:4] == '12':
                self.__contract_type = "next_quarter"
            else:
                self.__contract_type = None
                raise SymbolError("交易所: Huobi 交割合约ID错误，只支持当季与次季合约！")

    def get_single_equity(self, symbol):
        """
        获取单个合约账户的权益
        :param symbol: 例如"BTC","ETH"...
        :return:返回浮点数
        """
        data = self.__huobi_futures.get_contract_account_info(symbol=symbol)
        result =float(data["data"][0]["margin_balance"])
        return result

    def buy(self, price, size, order_type=None):
        """
        火币交割合约下单买入开多
        :param price:   下单价格
        :param size:    下单数量
        :param order_type:  0：限价单
                            1：只做Maker（Post only）
                            2：全部成交或立即取消（FOK）
                            3：立即成交并取消剩余（IOC）
                            4：对手价下单
        :return:
        """
        if config.backtest != "enabled":
            order_type = order_type or 0
            if order_type == 0:
                order_price_type = 'limit'
            elif order_type == 1:
                order_price_type = "post_only"
            elif order_type == 2:
                order_price_type = "fok"
            elif order_type == 3:
                order_price_type = "ioc"
            elif order_type == 4:
                order_price_type = "opponent"
            else:
                return "【交易提醒】交易所：Huobi 交割合约订单报价类型错误！"
            result = self.__huobi_futures.send_contract_order(symbol=self.__symbol, contract_type=self.__contract_type, contract_code=self.__contract_code,
                            client_order_id='', price=price, volume=size, direction='buy',
                            offset='open', lever_rate=self.__leverage, order_price_type=order_price_type)
            try:
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
            except Exception as e:
                raise SendOrderError(result['err_msg'])
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id = result['data']['order_id_str'])
                            state = self.get_order_info(order_id = result['data']['order_id_str'])
                            if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id = result['data']['order_id_str'])
                            state = self.get_order_info(order_id = result['data']['order_id_str'])
                            if state['订单状态'] == "部分成交撤销":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id = result['data']['order_id_str'])
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:
                        self.revoke_order(order_id = result['data']['order_id_str'])
                        state = self.get_order_info(order_id = result['data']['order_id_str'])
                        if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id = result['data']['order_id_str'])
                        state = self.get_order_info(order_id = result['data']['order_id_str'])
                        if state['订单状态'] == "部分成交撤销":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id = result['data']['order_id_str'])
                    state = self.get_order_info(order_id = result['data']['order_id_str'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:
            return "回测模拟下单成功！"


    def sell(self, price, size, order_type=None):
        """
        火币交割合约下单卖出平多
        :param price:   下单价格
        :param size:    下单数量
        :param order_type:  0：限价单
                            1：只做Maker（Post only）
                            2：全部成交或立即取消（FOK）
                            3：立即成交并取消剩余（IOC）
                            4：对手价下单
        :return:
        """
        if config.backtest != "enabled":
            order_type = order_type or 0
            if order_type == 0:
                order_price_type = 'limit'
            elif order_type == 1:
                order_price_type = "post_only"
            elif order_type == 2:
                order_price_type = "fok"
            elif order_type == 3:
                order_price_type = "ioc"
            elif order_type == 4:
                order_price_type = "opponent"
            else:
                return "【交易提醒】交易所: Huobi 交割合约订单报价类型错误！"
            result = self.__huobi_futures.send_contract_order(symbol=self.__symbol, contract_type=self.__contract_type, contract_code=self.__contract_code,
                            client_order_id='', price=price, volume=size, direction='sell',
                            offset='close', lever_rate=self.__leverage, order_price_type=order_price_type)
            try:
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
            except Exception as e:
                raise SendOrderError(result['err_msg'])
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "部分成交撤销":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "部分成交撤销":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['data']['order_id_str'])
                    state = self.get_order_info(order_id=result['data']['order_id_str'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:
            return "回测模拟下单成功！"

    def buytocover(self, price, size, order_type=None):
        """
        火币交割合约下单买入平空
        :param price:   下单价格
        :param size:    下单数量
        :param order_type:  0：限价单
                            1：只做Maker（Post only）
                            2：全部成交或立即取消（FOK）
                            3：立即成交并取消剩余（IOC）
                            4：对手价下单
        :return:
        """
        if config.backtest != "enabled":
            order_type = order_type or 0
            if order_type == 0:
                order_price_type = 'limit'
            elif order_type == 1:
                order_price_type = "post_only"
            elif order_type == 2:
                order_price_type = "fok"
            elif order_type == 3:
                order_price_type = "ioc"
            elif order_type == 4:
                order_price_type = "opponent"
            else:
                return "【交易提醒】交易所: Huobi交割合约订单报价类型错误！"
            result = self.__huobi_futures.send_contract_order(symbol=self.__symbol, contract_type=self.__contract_type, contract_code=self.__contract_code,
                            client_order_id='', price=price, volume=size, direction='buy',
                            offset='close', lever_rate=self.__leverage, order_price_type=order_price_type)
            try:
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
            except Exception as e:
                raise SendOrderError(result['err_msg'])
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "部分成交撤销":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state['已成交数量'])
                    except:
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "部分成交撤销":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['data']['order_id_str'])
                    state = self.get_order_info(order_id=result['data']['order_id_str'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:
            return "回测模拟下单成功！"

    def sellshort(self, price, size, order_type=None):
        """
        火币交割合约下单卖出开空
        :param price:   下单价格
        :param size:    下单数量
        :param order_type:  0：限价单
                            1：只做Maker（Post only）
                            2：全部成交或立即取消（FOK）
                            3：立即成交并取消剩余（IOC）
                            4：对手价下单
        :return:
        """
        if config.backtest != "enabled":
            order_type = order_type or 0
            if order_type == 0:
                order_price_type = 'limit'
            elif order_type == 1:
                order_price_type = "post_only"
            elif order_type == 2:
                order_price_type = "fok"
            elif order_type == 3:
                order_price_type = "ioc"
            elif order_type == 4:
                order_price_type = "opponent"
            else:
                return "【交易提醒】交易所: Huobi 订单报价类型错误！"
            result = self.__huobi_futures.send_contract_order(symbol=self.__symbol, contract_type=self.__contract_type, contract_code=self.__contract_code,
                            client_order_id='', price=price, volume=size, direction='sell',
                            offset='open', lever_rate=self.__leverage, order_price_type=order_price_type)
            try:
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
            except Exception as e:
                raise SendOrderError(result['err_msg'])
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state['已成交数量'])
                        except:
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "部分成交撤销":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "部分成交撤销":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['data']['order_id_str'])
                    state = self.get_order_info(order_id=result['data']['order_id_str'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:
            return "回测模拟下单成功！"

    def BUY(self, cover_short_price, cover_short_size, open_long_price, open_long_size, order_type=None):
        """火币交割合约平空开多"""
        if config.backtest != "enabled":
            receipt1 = self.buytocover(cover_short_price, cover_short_size, order_type)
            if "完全成交" in str(receipt1):
                receipt2 = self.buy(open_long_price, open_long_size, order_type)
                return {"平仓结果": receipt1, "开仓结果": receipt2}
            else:
                return receipt1
        else:
            return "回测模拟下单成功！"

    def SELL(self, cover_long_price, cover_long_size, open_short_price, open_short_size, order_type=None):
        """火币交割合约平多开空"""
        if config.backtest != "enabled":
            receipt1 = self.sell(cover_long_price, cover_long_size, order_type)
            if "完全成交" in str(receipt1):
                receipt2 = self.sellshort(open_short_price, open_short_size, order_type)
                return {"平仓结果": receipt1, "开仓结果": receipt2}
            else:
                return receipt1
        else:
            return "回测模拟下单成功！"

    def revoke_order(self, order_id):
        receipt = self.__huobi_futures.cancel_contract_order(self.__symbol, order_id)
        if receipt['status'] == "ok":
            return '【交易提醒】交易所: Huobi 撤单成功'
        else:
            return '【交易提醒】交易所: Huobi 撤单失败' + receipt['data']['errors'][0]['err_msg']

    def get_order_info(self, order_id):
        result = self.__huobi_futures.get_contract_order_info(self.__symbol, order_id)
        instrument_id = result['data'][0]['contract_code']
        state = int(result['data'][0]['status'])
        avg_price = result['data'][0]['trade_avg_price']
        amount = result['data'][0]['trade_volume']
        turnover = result['data'][0]['trade_turnover']
        if result['data'][0]['direction'] == "buy" and result['data'][0]['offset'] == "open":
            action = "买入开多"
        elif result['data'][0]['direction'] == "buy" and result['data'][0]['offset'] == "close":
            action = "买入平空"
        elif result['data'][0]['direction'] == "sell" and result['data'][0]['offset'] == "open":
            action = "卖出开空"
        elif result['data'][0]['direction'] == "sell" and result['data'][0]['offset'] == "close":
            action = "卖出平多"
        else:
            action = "交易方向错误！"
        if state == 6:
            dict = {"交易所": "Huobi交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "完全成交",
                    "成交均价": avg_price, "已成交数量": amount, "成交金额": turnover}
            return dict
        elif state == 1:
            dict = {"交易所": "Huobi交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "准备提交"}
            return dict
        elif state == 7:
            dict = {"交易所": "Huobi交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "撤单成功",
                    "成交均价": avg_price, "已成交数量": amount, "成交金额": turnover}
            return dict
        elif state == 2:
            dict = {"交易所": "Huobi交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "准备提交"}
            return dict
        elif state == 4:
            dict = {"交易所": "Huobi交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "部分成交",
                    "成交均价": avg_price, "已成交数量": amount, "成交金额": turnover}
            return dict
        elif state == 3:
            dict = {"交易所": "Huobi交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "已提交"}
            return dict
        elif state == 11:
            dict = {"交易所": "Huobi交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "撤单中"}
            return dict
        elif state == 5:
            dict = {"交易所": "Huobi交割合约", "合约ID": instrument_id, "方向": action, "订单状态": "部分成交撤销",
                    "成交均价": avg_price, "已成交数量": amount, "成交金额": turnover}
            return dict

    def get_kline(self, time_frame):
        if time_frame == '1m' or time_frame == '1M':
            period = '1min'
        elif time_frame == '5m' or time_frame == '5M':
            period = '5min'
        elif time_frame == '15m' or time_frame == '15M':
            period = '15min'
        elif time_frame == '30m' or time_frame == '30M':
            period = '30min'
        elif time_frame == '1h' or time_frame == '1H':
            period = '60min'
        elif time_frame == '4h' or time_frame == '4H':
            period = '4hour'
        elif time_frame == '1d' or time_frame == '1D':
            period = '1day'
        else:
            raise KlineError("k线周期错误，k线周期只能是【1m, 5m, 15m, 30m, 1h, 4h, 1d】!")
        records = self.__huobi_futures.get_contract_kline(symbol=self.__contract_code, period=period)['data']
        list = []
        for item in records:
            item = [ts_to_utc_str(item['id']), item['open'], item['high'], item['low'], item['close'], item['vol'], round(item['amount'], 2)]
            list.append(item)
        list.reverse()
        return list

    def get_position(self, mode=None):
        receipt = self.__huobi_futures.get_contract_position_info(self.__symbol)
        if mode == "both":
            if receipt['data'] == []:
                return {"long": {"price": 0, "amount": 0}, "short": {"price": 0, "amount": 0}}
            elif len(receipt['data']) == 1:
                if receipt['data'][0]['direction'] == "buy":
                    return {"long": {"price": receipt['data'][0]['cost_hold'], "amount": receipt['data'][0]['volume']}, "short": {"price": 0, "amount": 0}}
                elif receipt['data'][0]['direction'] == "sell":
                    return {"short": {"price": receipt['data'][0]['cost_hold'], "amount": receipt['data'][0]['volume']}, "long": {"price": 0, "amount": 0}}
            elif len(receipt['data']) == 2:
                return {
                    "long": {
                        "price": receipt['data'][0]['cost_hold'], "amount": receipt['data'][0]['volume']
                    },
                        "short": {
                            "price": receipt['data'][1]['cost_hold'], "amount": receipt['data'][1]['volume']
                        }
                }
        else:
            if receipt['data'] != []:
                direction = receipt['data'][0]['direction']
                amount = receipt['data'][0]['volume']
                price = receipt['data'][0]['cost_hold']
                if amount > 0 and direction == "buy":
                    dict = {'direction': 'long', 'amount': amount, 'price': price}
                    return dict
                elif amount > 0 and direction == "sell":
                    dict = {'direction': 'short', 'amount': amount, 'price': price}
                    return dict
            else:
                dict = {'direction': 'none', 'amount': 0, 'price': 0.0}
                return dict

    def get_ticker(self):
        receipt = self.__huobi_futures.get_contract_market_merged(self.__contract_code)
        last = receipt['tick']['close']
        return {"last": last}

    def get_contract_value(self):
        receipt = self.__huobi_futures.get_contract_info()
        for item in receipt['data']:
            if item["contract_code"] == self.__contract_code:
                contract_value = item["contract_size"]
                return contract_value

    def get_depth(self, type=None):
        """
        火币交割合约获取深度数据
        :param type: 如不传参，返回asks和bids；只获取asks传入type="asks"；只获取"bids"传入type="bids"
        :return:返回20档深度数据
        """
        response = self.__huobi_futures.get_contract_depth(self.__contract_code, type="step0")
        asks_list = response["tick"]["asks"]
        bids_list = response["tick"]["bids"]
        asks = []
        bids = []
        for i in asks_list:
            asks.append(float(i[0]))
        for j in bids_list:
            bids.append(float(j[0]))
        if type == "asks":
            return asks
        elif type == "bids":
            return bids
        else:
            return response

class HUOBISWAP:
    """火币永续合约 https://docs.huobigroup.com/docs/coin_margined_swap/v1/cn/#5ea2e0cde2"""

    def __init__(self, access_key, secret_key, instrument_id, leverage=None):
        """
        :param access_key:
        :param secret_key:
        :param instrument_id: 'BTC-USD-SWAP'
        :param leverage:杠杆倍数，如不填则默认设置为20倍
        """
        self.__access_key = access_key
        self.__secret_key = secret_key
        self.__instrument_id = "{}-{}".format(instrument_id.split("-")[0], instrument_id.split("-")[1])
        self.__huobi_swap = huobiswap.HuobiSwap(self.__access_key, self.__secret_key)
        self.__leverage = leverage or 20

    def get_single_equity(self, contract_code):
        """
        获取单个合约账户的权益
        :param contract_code: 例如 "BTC-USD"
        :return:返回浮点数
        """
        data = self.__huobi_swap.get_contract_account_info(contract_code=contract_code)
        result =float(data["data"][0]["margin_balance"])
        return result

    def buy(self, price, size, order_type=None):
        """
        火币永续合约下单买入开多
        :param price:   下单价格
        :param size:    下单数量
        :param order_type:  0：限价单
                            1：只做Maker（Post only）
                            2：全部成交或立即取消（FOK）
                            3：立即成交并取消剩余（IOC）
                            4：对手价下单
        :return:
        """
        if config.backtest != "enabled":
            order_type = order_type or 0
            if order_type == 0:
                order_price_type = 'limit'
            elif order_type == 1:
                order_price_type = "post_only"
            elif order_type == 2:
                order_price_type = "fok"
            elif order_type == 3:
                order_price_type = "ioc"
            elif order_type == 4:
                order_price_type = "opponent"
            else:
                return "【交易提醒】交易所: Huobi 订单报价类型错误！"
            result = self.__huobi_swap.send_contract_order(contract_code=self.__instrument_id,
                            client_order_id='', price=price, volume=size, direction='buy',
                            offset='open', lever_rate=self.__leverage, order_price_type=order_price_type)
            try:
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
            except:
                raise SendOrderError(result['err_msg'])
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:    # 如果撤单成功，重发委托
                        if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except: # 如果撤单失败，就再查询一次订单状态然后返回结果
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "部分成交撤销":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except: # 如果撤单失败，就再查询一次订单状态然后返回结果
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "部分成交撤销":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except: # 如果撤单失败，就再查询一次订单状态然后返回结果
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['data']['order_id_str'])
                    state = self.get_order_info(order_id=result['data']['order_id_str'])
                    return {"【交易提醒】下单结果": state}
                except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                    order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:
            return "回测模拟下单成功！"

    def sell(self, price, size, order_type=None, lever_rate=None):
        """
        火币永续合约下单卖出平多
        :param price:   下单价格
        :param size:    下单数量
        :param order_type:  0：限价单
                            1：只做Maker（Post only）
                            2：全部成交或立即取消（FOK）
                            3：立即成交并取消剩余（IOC）
                            4：对手价下单
        :return:
        """
        if config.backtest != "enabled":
            order_type = order_type or 0
            if order_type == 0:
                order_price_type = 'limit'
            elif order_type == 1:
                order_price_type = "post_only"
            elif order_type == 2:
                order_price_type = "fok"
            elif order_type == 3:
                order_price_type = "ioc"
            elif order_type == 4:
                order_price_type = "opponent"
            else:
                return "【交易提醒】交易所: Huobi 订单报价类型错误！"
            result = self.__huobi_swap.send_contract_order(contract_code=self.__instrument_id,
                            client_order_id='', price=price, volume=size, direction='sell',
                            offset='close', lever_rate=self.__leverage, order_price_type=order_price_type)
            try:
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
            except:
                raise SendOrderError(result['err_msg'])
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "撤单成功" or state["订单状态"] == "部分成交撤销":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "部分成交撤销":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "撤单成功" or state["订单状态"] == "部分成交撤销":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "部分成交撤销":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['data']['order_id_str'])
                    state = self.get_order_info(order_id=result['data']['order_id_str'])
                    return {"【交易提醒】下单结果": state}
                except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                    order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:
            return "回测模拟下单成功！"

    def buytocover(self, price, size, order_type=None, lever_rate=None):
        """
        火币永续合约下单买入平空
        :param price:   下单价格
        :param size:    下单数量
        :param order_type:  0：限价单
                            1：只做Maker（Post only）
                            2：全部成交或立即取消（FOK）
                            3：立即成交并取消剩余（IOC）
                            4：对手价下单
        :return:
        """
        if config.backtest != "enabled":
            order_type = order_type or 0
            if order_type == 0:
                order_price_type = 'limit'
            elif order_type == 1:
                order_price_type = "post_only"
            elif order_type == 2:
                order_price_type = "fok"
            elif order_type == 3:
                order_price_type = "ioc"
            elif order_type == 4:
                order_price_type = "opponent"
            else:
                return "【交易提醒】交易所: Huobi 订单报价类型错误！"
            result = self.__huobi_swap.send_contract_order(contract_code=self.__instrument_id,
                            client_order_id='', price=price, volume=size, direction='buy',
                            offset='close', lever_rate=self.__leverage, order_price_type=order_price_type)
            try:
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
            except:
                raise SendOrderError(result['err_msg'])
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "撤单成功" or state["订单状态"] == "部分成交撤销":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "部分成交撤销":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "撤单成功" or state["订单状态"] == "部分成交撤销":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "部分成交撤销":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['data']['order_id_str'])
                    state = self.get_order_info(order_id=result['data']['order_id_str'])
                    return {"【交易提醒】下单结果": state}
                except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                    order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:
            return "回测模拟下单成功！"

    def sellshort(self, price, size, order_type=None, lever_rate=None):
        """
        火币永续合约下单卖出开空
        :param price:   下单价格
        :param size:    下单数量
        :param order_type:  0：限价单
                            1：只做Maker（Post only）
                            2：全部成交或立即取消（FOK）
                            3：立即成交并取消剩余（IOC）
                            4：对手价下单
        :return:
        """
        if config.backtest != "enabled":
            order_type = order_type or 0
            if order_type == 0:
                order_price_type = 'limit'
            elif order_type == 1:
                order_price_type = "post_only"
            elif order_type == 2:
                order_price_type = "fok"
            elif order_type == 3:
                order_price_type = "ioc"
            elif order_type == 4:
                order_price_type = "opponent"
            else:
                return "【交易提醒】交易所: Huobi 订单报价类型错误！"
            result = self.__huobi_swap.send_contract_order(contract_code=self.__instrument_id,
                            client_order_id='', price=price, volume=size, direction='sell',
                            offset='open', lever_rate=self.__leverage, order_price_type=order_price_type)
            try:
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
            except:
                raise SendOrderError(result['err_msg'])
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "撤单成功" or state["订单状态"] == "部分成交撤销":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data']['order_id_str'])
                            state = self.get_order_info(order_id=result['data']['order_id_str'])
                            if state['订单状态'] == "部分成交撤销":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                            order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['data']['order_id_str'])
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "撤单成功" or state["订单状态"] == "部分成交撤销":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['data']['order_id_str'])
                        state = self.get_order_info(order_id=result['data']['order_id_str'])
                        if state['订单状态'] == "部分成交撤销":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                        order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['data']['order_id_str'])
                    state = self.get_order_info(order_id=result['data']['order_id_str'])
                    return {"【交易提醒】下单结果": state}
                except:  # 如果撤单失败，就再查询一次订单状态然后返回结果
                    order_info = self.get_order_info(order_id=result['data']['order_id_str'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:
            return "回测模拟下单成功！"

    def BUY(self, cover_short_price, cover_short_size, open_long_price, open_long_size, order_type=None):
        """火币交割合约平空开多"""
        if config.backtest != "enabled":
            order_type = order_type or 0
            receipt1 = self.buytocover(cover_short_price, cover_short_size, order_type)
            if "完全成交" in str(receipt1):
                receipt2 = self.buy(open_long_price, open_long_size, order_type)
                return {"平仓结果": receipt1, "开仓结果": receipt2}
            else:
                return receipt1
        else:
            return "回测模拟下单成功！"

    def SELL(self, cover_long_price, cover_long_size, open_short_price, open_short_size, order_type=None):
        """火币交割合约平多开空"""
        if config.backtest != "enabled":
            order_type = order_type or 0
            receipt1 = self.sell(cover_long_price, cover_long_size, order_type)
            if "完全成交" in str(receipt1):
                receipt2 = self.sellshort(open_short_price, open_short_size, order_type)
                return {"平仓结果": receipt1, "开仓结果": receipt2}
            else:
                return receipt1
        else:
            return "回测模拟下单成功！"

    def revoke_order(self, order_id):
        receipt = self.__huobi_swap.cancel_contract_order(self.__instrument_id, order_id)
        if receipt['status'] == "ok":
            return '【交易提醒】交易所: Huobi 撤单成功'
        else:
            return '【交易提醒】交易所: Huobi 撤单失败' + receipt['data']['errors'][0]['err_msg']

    def get_order_info(self, order_id):
        result = self.__huobi_swap.get_contract_order_info(self.__instrument_id, order_id)
        instrument_id = self.__instrument_id
        state = int(result['data'][0]['status'])
        avg_price = result['data'][0]['trade_avg_price']
        amount = result['data'][0]['trade_volume']
        turnover = result['data'][0]['trade_turnover']
        if result['data'][0]['direction'] == "buy" and result['data'][0]['offset'] == "open":
            action = "买入开多"
        elif result['data'][0]['direction'] == "buy" and result['data'][0]['offset'] == "close":
            action = "买入平空"
        elif result['data'][0]['direction'] == "sell" and result['data'][0]['offset'] == "open":
            action = "卖出开空"
        elif result['data'][0]['direction'] == "sell" and result['data'][0]['offset'] == "close":
            action = "卖出平多"
        else:
            action = "交易方向错误！"
        if state == 6:
            dict = {"交易所": "Huobi永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "完全成交",
                    "成交均价": avg_price, "已成交数量": amount, "成交金额": turnover}
            return dict
        elif state == 1:
            dict = {"交易所": "Huobi永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "准备提交"}
            return dict
        elif state == 7:
            dict = {"交易所": "Huobi永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "撤单成功",
                    "成交均价": avg_price, "已成交数量": amount, "成交金额": turnover}
            return dict
        elif state == 2:
            dict = {"交易所": "Huobi永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "准备提交"}
            return dict
        elif state == 4:
            dict = {"交易所": "Huobi永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "部分成交",
                    "成交均价": avg_price, "已成交数量": amount, "成交金额": turnover}
            return dict
        elif state == 3:
            dict = {"交易所": "Huobi永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "已提交"}
            return dict
        elif state == 11:
            dict = {"交易所": "Huobi永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "撤单中"}
            return dict
        elif state == 5:
            dict = {"交易所": "Huobi永续合约", "合约ID": instrument_id, "方向": action, "订单状态": "部分成交撤销",
                    "成交均价": avg_price, "已成交数量": amount, "成交金额": turnover}
            return dict

    def get_kline(self, time_frame):
        if time_frame == '1m' or time_frame == '1M':
            period = '1min'
        elif time_frame == '5m' or time_frame == '5M':
            period = '5min'
        elif time_frame == '15m' or time_frame == '15M':
            period = '15min'
        elif time_frame == '30m' or time_frame == '30M':
            period = '30min'
        elif time_frame == '1h' or time_frame == '1H':
            period = '60min'
        elif time_frame == '4h' or time_frame == '4H':
            period = '4hour'
        elif time_frame == '1d' or time_frame == '1D':
            period = '1day'
        else:
            raise KlineError("交易所: Huobi k线周期错误，k线周期只能是【1m, 5m, 15m, 30m, 1h, 4h, 1d】!")
        records = self.__huobi_swap.get_contract_kline(self.__instrument_id, period=period)['data']
        list = []
        for item in records:
            item = [ts_to_utc_str(item['id']), item['open'], item['high'], item['low'], item['close'], item['vol'], round(item['amount'], 2)]
            list.append(item)
        list.reverse()
        return list

    def get_position(self, mode=None):
        receipt = self.__huobi_swap.get_contract_position_info(self.__instrument_id)
        if mode == "both":
            if receipt['data'] == []:
                return {"long": {"price": 0, "amount": 0}, "short": {"price": 0, "amount": 0}}
            elif len(receipt['data']) == 1:
                if receipt['data'][0]['direction'] == "buy":
                    return {"long": {"price": receipt['data'][0]['cost_hold'], "amount": receipt['data'][0]['volume']}, "short": {"price": 0, "amount": 0}}
                elif receipt['data'][0]['direction'] == "sell":
                    return {"short": {"price": receipt['data'][0]['cost_hold'], "amount": receipt['data'][0]['volume']}, "long": {"price": 0, "amount": 0}}
            elif len(receipt['data']) == 2:
                return {
                    "long": {
                        "price": receipt['data'][0]['cost_hold'], "amount": receipt['data'][0]['volume']
                    },
                        "short": {
                            "price": receipt['data'][1]['cost_hold'], "amount": receipt['data'][1]['volume']
                        }
                }
        else:
            if receipt['data'] != []:
                direction = receipt['data'][0]['direction']
                amount = receipt['data'][0]['volume']
                price = receipt['data'][0]['cost_hold']
                if amount > 0 and direction == "buy":
                    dict = {'direction': 'long', 'amount': amount, 'price': price}
                    return dict
                elif amount > 0 and direction == "sell":
                    dict = {'direction': 'short', 'amount': amount, 'price': price}
                    return dict
            else:
                dict = {'direction': 'none', 'amount': 0, 'price': 0.0}
                return dict

    def get_ticker(self):
        receipt = self.__huobi_swap.get_contract_market_merged(self.__instrument_id)
        last = receipt['tick']['close']
        return {"last": last}

    def get_contract_value(self):
        receipt = self.__huobi_swap.get_contract_info()
        for item in receipt['data']:
            if item["contract_code"] == self.__instrument_id:
                contract_value = item["contract_size"]
                return contract_value

    def get_depth(self, type=None):
        """
        火币永续合约获取深度数据
        :param type: 如不传参，返回asks和bids；只获取asks传入type="asks"；只获取"bids"传入type="bids"
        :return:返回20档深度数据
        """
        response = self.__huobi_swap.get_contract_depth(contract_code=self.__instrument_id, type="step0")
        asks_list = response["tick"]["asks"]
        bids_list = response["tick"]["bids"]
        asks = []
        bids = []
        for i in asks_list:
            asks.append(float(i[0]))
        for j in bids_list:
            bids.append(float(j[0]))
        if type == "asks":
            return asks
        elif type == "bids":
            return bids
        else:
            return response

class HUOBISPOT:
    """火币现货"""

    def __init__(self, access_key, secret_key, instrument_id):
        """

        :param access_key:
        :param secret_key:
        :param instrument_id: e.g. 'ETC-USDT'
        """
        self.__access_key = access_key
        self.__secret_key = secret_key
        self.__instrument_id = (instrument_id.split('-')[0] + instrument_id.split('-')[1]).lower()
        self.__huobi_spot = huobispot.HuobiSVC(self.__access_key, self.__secret_key)
        self.__currency = (instrument_id.split('-')[0]).lower()
        self.__account_id = self.__huobi_spot.get_accounts()['data'][0]['id']

    def get_single_equity(self, currency):
        """
        获取单个币种的权益
        :param currency: 例如 "USDT"
        :return:返回浮点数
        """
        data = self.__huobi_spot.get_balance_currency(acct_id=self.__account_id, currency=currency)
        result = float(data[currency])
        return result

    def buy(self, price, size, order_type=None):
        """
        火币现货买入开多
        :param price: 价格
        :param size: 数量
        :param order_type: 填 0或者不填都是限价单，
                            1：只做Maker（Post only）
                            2：全部成交或立即取消（FOK）
                            3：立即成交并取消剩余（IOC）
                            4.市价买入
        :return:
        """
        if config.backtest != "enabled":
            order_type=order_type or 'buy-limit'
            if order_type == 0:
                order_type = 'buy-limit'
            elif order_type == 1:
                order_type = 'buy-limit-maker'
            elif order_type == 2:
                order_type = 'buy-limit-fok'
            elif order_type == 3:
                order_type = 'buy-ioc'
            elif order_type == 4:
                order_type = 'buy-market'
            result = self.__huobi_spot.send_order(self.__account_id, size, 'spot-api', self.__instrument_id, _type=order_type, price=price)
            if result["status"] == "error": # 如果下单失败就抛出异常
                raise SendOrderError(result["err-msg"])
            order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data'])
                            state = self.get_order_info(order_id=result['data'])
                            if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data'])
                            state = self.get_order_info(order_id=result['data'])
                            if state['订单状态'] == "部分成交撤销":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['data'])
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:
                        self.revoke_order(order_id=result['data'])
                        state = self.get_order_info(order_id=result['data'])
                        if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['data'])
                        state = self.get_order_info(order_id=result['data'])
                        if state['订单状态'] == "部分成交撤销":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['data'])
                    state = self.get_order_info(order_id=result['data'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:
            return "回测模拟下单成功！"

    def sell(self, price, size, order_type=None):
        """
        火币现货卖出平多
        :param price: 价格
        :param size: 数量
        :param order_type: 填 0或者不填都是限价单，
                            1：只做Maker（Post only）
                            2：全部成交或立即取消（FOK）
                            3：立即成交并取消剩余（IOC）
                            4.市价卖出
        :return:
        """
        if config.backtest != "enabled":
            order_type=order_type or 'sell-limit'
            if order_type == 0:
                order_type = 'sell-limit'
            elif order_type == 1:
                order_type = 'sell-limit-maker'
            elif order_type == 2:
                order_type = 'sell-limit-fok'
            elif order_type == 3:
                order_type = 'sell-ioc'
            elif order_type == 4:
                order_type = 'sell-market'
            result = self.__huobi_spot.send_order(self.__account_id, size, 'spot-api', self.__instrument_id, _type=order_type, price=price)
            if result["status"] == "error":  # 如果下单失败就抛出异常
                raise SendOrderError(result["err-msg"])
            order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data'])
                            state = self.get_order_info(order_id=result['data'])
                            if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['data'])
                            state = self.get_order_info(order_id=result['data'])
                            if state['订单状态'] == "部分成交撤销":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['data'])
                if order_info["订单状态"] == "准备提交" or order_info["订单状态"] == "已提交":
                    try:
                        self.revoke_order(order_id=result['data'])
                        state = self.get_order_info(order_id=result['data'])
                        if state['订单状态'] == "撤单成功" or state['订单状态'] == "部分成交撤销":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['data'])
                        state = self.get_order_info(order_id=result['data'])
                        if state['订单状态'] == "部分成交撤销":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['data'])
                    state = self.get_order_info(order_id=result['data'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['data'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:
            return "回测模拟下单成功！"

    def get_order_info(self, order_id):
        result = self.__huobi_spot.order_info(order_id)
        instrument_id = self.__instrument_id
        action = None
        try:
            if "buy" in result['data']['type']:
                action = "买入开多"
            elif  "sell" in result['data']['type']:
                action = "卖出平多"
        except Exception as e:
            raise GetOrderError(e)

        if result["data"]['state'] == 'filled':
            dict = {"交易所": "Huobi现货", "合约ID": instrument_id, "方向": action, "订单状态": "完全成交",
                    "成交均价": float(result['data']['price']),
                    "已成交数量": float(result["data"]["field-amount"]),
                    "成交金额": float(result['data']["field-cash-amount"])}
            return dict
        elif result["data"]['state'] == 'canceled':
            dict = {"交易所": "Huobi现货", "合约ID": instrument_id, "方向": action, "订单状态": "撤单成功",
                    "成交均价": float(result['data']['price']),
                    "已成交数量": float(result["data"]["field-amount"]),
                    "成交金额": float(result['data']["field-cash-amount"])}
            return dict
        elif result["data"]['state'] == 'partial-filled':
            dict = {"交易所": "Huobi现货", "合约ID": instrument_id, "方向": action, "订单状态": "部分成交",
                    "成交均价": float(result['data']['price']),
                    "已成交数量": float(result["data"]["field-amount"]),
                    "成交金额": float(result['data']["field-cash-amount"])}
            return dict
        elif result["data"]['state'] == 'partial-canceled':
            dict = {"交易所": "Huobi现货", "合约ID": instrument_id, "方向": action, "订单状态": "部分成交撤销",
                    "成交均价": float(result['data']['price']),
                    "已成交数量": float(result["data"]["field-amount"]),
                    "成交金额": float(result['data']["field-cash-amount"])}
            return dict
        elif result["data"]['state'] == 'submitted':
            dict = {"交易所": "Huobi现货", "合约ID": instrument_id, "方向": action, "订单状态": "已提交"}
            return dict

    def revoke_order(self, order_id):
        receipt = self.__huobi_spot.cancel_order(order_id)
        if receipt['status'] == "ok":
            return '【交易提醒】交易所: Huobi 撤单成功'
        else:
            return '【交易提醒】交易所: Huobi 撤单失败' + receipt['data']['errors'][0]['err_msg']

    def get_kline(self, time_frame):
        if time_frame == '1m' or time_frame == '1M':
            period = '1min'
        elif time_frame == '5m' or time_frame == '5M':
            period = '5min'
        elif time_frame == '15m' or time_frame == '15M':
            period = '15min'
        elif time_frame == '30m' or time_frame == '30M':
            period = '30min'
        elif time_frame == '1h' or time_frame == '1H':
            period = '60min'
        elif time_frame == '4h' or time_frame == '4H':
            period = '4hour'
        elif time_frame == '1d' or time_frame == '1D':
            period = '1day'
        else:
            raise KlineError("交易所: Huobi k线周期错误，k线周期只能是【1m, 5m, 15m, 30m, 1h, 4h, 1d】!")
        records = self.__huobi_spot.get_kline(self.__instrument_id, period=period)['data']
        length = len(records)
        list = []
        for item in records:
            item = [ts_to_utc_str(item['id']), item['open'], item['high'], item['low'], item['close'], item['vol'],
                    round(item['amount'], 2)]
            list.append(item)
        return list

    def get_position(self):
        """获取当前交易对的计价货币的可用余额，如当前交易对为etc-usdt, 则获取的是etc的可用余额"""
        receipt = self.__huobi_spot.get_balance_currency(self.__account_id, self.__currency)
        direction = 'long'
        amount = receipt[self.__currency]
        price = None
        result = {'direction': direction, 'amount': amount, 'price': price}
        return result

    def get_ticker(self):
        receipt = self.__huobi_spot.get_ticker(self.__instrument_id)
        last = receipt['tick']['close']
        return {"last": last}

    def get_depth(self, type=None, size=None):
        """
        火币现货获取深度数据
        :param type: 如不传参，返回asks和bids；只获取asks传入type="asks"；只获取"bids"传入type="bids"
        :param size: 返回深度档位数量，取值范围：5，10，20，默认10档
        :return:
        """
        size = size or 10
        response = self.__huobi_spot.get_depth(self.__instrument_id, depth=size, type="step0")
        asks_list = response["tick"]["asks"]
        bids_list = response["tick"]["bids"]
        asks = []
        bids = []
        for i in asks_list:
            asks.append(float(i[0]))
        for j in bids_list:
            bids.append(float(j[0]))
        if type == "asks":
            return asks
        elif type == "bids":
            return bids
        else:
            return response


class BINANCESPOT:
    """币安现货rest api"""

    def __init__(self, access_key, secret_key, symbol):
        """
        初始化
        :param access_key: api_key
        :param secret_key: secret_key
        :param symbol: 币对，例如："EOS-USDT"
        """
        self.__access_key = access_key
        self.__secret_key = secret_key
        self.__instrument_id = symbol.split("-")[0] + symbol.split("-")[1]
        self.__currency = symbol.split("-")[0]
        self.__binance_spot = binance_spot
        self.__binance_spot.set(self.__access_key, self.__secret_key)   # 设置api

    def get_single_equity(self, currency):
        """
        获取单个币种的权益
        :param currency: 例如 "USDT"
        :return:返回浮点数
        """
        data = self.__binance_spot.balances()
        for i in data:
            if i == currency:
                balance = float(data[currency]["free"])
                return balance

    def buy(self, price, size, order_type=None, timeInForce=None):
        """
        币安现货买入
        :param price: 价格
        :param size: 数量
        :param order_type:默认限价单，LIMIT 限价单
                                    MARKET 市价单
                                    STOP_LOSS 止损单
                                    STOP_LOSS_LIMIT 限价止损单
                                    TAKE_PROFIT 止盈单
                                    TAKE_PROFIT_LIMIT 限价止盈单
                                    LIMIT_MAKER 限价卖单
        :param timeInForce:有效方式，定义了订单多久能够变成失效。
                            GTC	成交为止订单会一直有效，直到被成交或者取消。
                            IOC	无法立即成交的部分就撤销，订单在失效前会尽量多的成交。
                            FOK	无法全部立即成交就撤销，如果无法全部成交，订单会失效。
        :return:
        """
        if config.backtest != "enabled":  # 实盘模式
            order_type = "LIMIT" if order_type is None else order_type  # 默认限价单
            timeInForce = "GTC" if timeInForce is None else timeInForce  # 默认成交为止，订单会一直有效，直到被成交或者取消。
            result = self.__binance_spot.order(symbol=self.__instrument_id,
                                               side="BUY",
                                               quantity=size,
                                               price=price,
                                               orderType=order_type,
                                               timeInForce=timeInForce)
            if "msg" in str(result):   # 如果下单失败就抛出异常，提示错误信息。
                raise SendOrderError(result["msg"])
            order_info = self.get_order_info(order_id=result['orderId'])   # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                                size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['orderId'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['orderId'])
                    state = self.get_order_info(order_id=result['orderId'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def sell(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            order_type = "LIMIT" if order_type is None else order_type  # 默认限价单
            timeInForce = "GTC" if timeInForce is None else timeInForce  # 默认成交为止，订单会一直有效，直到被成交或者取消。
            result = self.__binance_spot.order(symbol=self.__instrument_id,
                                               side="SELL",
                                               quantity=size,
                                               price=price,
                                               orderType=order_type,
                                               timeInForce=timeInForce)
            if "msg" in str(result):   # 如果下单失败就抛出异常，提示错误信息。
                raise SendOrderError(result["msg"])
            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                                size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['orderId'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['orderId'])
                    state = self.get_order_info(order_id=result['orderId'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def get_order_info(self, order_id):
        """币安现货查询订单信息"""
        result = self.__binance_spot.orderStatus(symbol=self.__instrument_id, orderId=order_id)
        if "msg" in str(result):
            return self.get_order_info(order_id)
        instrument_id = self.__instrument_id
        action = None
        if result['side'] == 'BUY':
            action = "买入开多"
        elif result['side'] == 'SELL':
            action = "卖出平多"

        if result['status'] == "FILLED":
            dict = {"交易所": "币安现货", "币对": instrument_id, "方向": action, "订单状态": "完全成交",
                    "成交均价": float(result['price']),
                    "已成交数量": float(result['executedQty']),
                    "成交金额": float(result["cummulativeQuoteQty"])}
            return dict
        elif result['status'] == "REJECTED":
            dict = {"交易所": "币安现货", "币对": instrument_id, "方向": action, "订单状态": "失败"}
            return dict
        elif result['status'] == "CANCELED":
            dict = {"交易所": "币安现货", "币对": instrument_id, "方向": action, "订单状态": "撤单成功",
                    "成交均价": float(result['price']),
                    "已成交数量": float(result['executedQty']),
                    "成交金额": float(result["cummulativeQuoteQty"])}
            return dict
        elif result['status'] == "NEW":
            dict = {"交易所": "币安现货", "币对": instrument_id, "方向": action, "订单状态": "等待成交"}
            return dict
        elif result['status'] == "PARTIALLY_FILLED":
            dict = {"交易所": "币安现货", "币对": instrument_id, "方向": action, "订单状态": "部分成交",
                    "成交均价": float(result['price']),
                    "已成交数量": float(result['executedQty']),
                    "成交金额": float(result["cummulativeQuoteQty"])}
            return dict
        elif result['status'] == "EXPIRED":
            dict = {"交易所": "币安现货", "币对": instrument_id, "方向": action, "订单状态": "订单被交易引擎取消",
                    "成交均价": float(result['price']),
                    "已成交数量": float(result['executedQty']),
                    "成交金额": float(result["cummulativeQuoteQty"])}
            return dict
        elif result['status'] == "PENDING_CANCEL	":
            dict = {"交易所": "币安现货", "币对": instrument_id, "方向": action, "订单状态": "撤单中"}
            return dict

    def revoke_order(self, order_id):
        """币安现货撤销订单"""
        receipt = self.__binance_spot.cancel(self.__instrument_id, orderId=order_id)
        if receipt['status'] == "CANCELED":
            return '【交易提醒】撤单成功'
        else:
            return '【交易提醒】撤单失败'

    def get_ticker(self):
        """币安现货查询最新价"""
        response = self.__binance_spot.get_ticker(self.__instrument_id)
        receipt = {'symbol': response['symbol'], 'last': response['price']}
        return receipt

    def get_kline(self, time_frame):
        """
        币安现货获取k线数据
        :param time_frame: k线周期。1m， 3m， 5m， 15m， 30m， 1h， 2h， 4h， 6h， 8h， 12h， 1d， 3d， 1w， 1M
        :return:返回一个列表，包含开盘时间戳、开盘价、最高价、最低价、收盘价、成交量。
        """
        receipt = self.__binance_spot.klines(self.__instrument_id, time_frame)  # 获取历史k线数据
        last_kine = self.__binance_spot.get_last_kline(self.__instrument_id)    # 获取24hr 价格变动情况
        for item in receipt:
            item[0] = ts_to_utc_str(int(item[0])/1000)
            item.pop(6)
            item.pop(7)
            item.pop(8)
            item.pop(6)
            item.pop(7)
            item.pop(6)
        receipt.append(last_kine)
        receipt.reverse()
        return receipt

    def get_position(self):
        """
        币安现货获取持仓信息
        :return: 返回一个字典，{'direction': direction, 'amount': amount, 'price': price}
        """
        receipt = self.__binance_spot.balances()[self.__currency]
        direction = 'long'
        amount = receipt['free']
        price = None
        result = {'direction': direction, 'amount': amount, 'price': price}
        return result

    def get_depth(self, type=None):
        """
        币安现货获取深度数据
        :param type: 如不传参，返回asks和bids；只获取asks传入type="asks"；只获取"bids"传入type="bids"
        :return:返回10档深度数据
        """
        response = self.__binance_spot.depth(self.__instrument_id)
        asks_list = response["asks"]
        bids_list = response["bids"]
        asks = []
        bids = []
        for i in asks_list:
            asks.append(float(i[0]))
        for j in bids_list:
            bids.append(float(j[0]))
        if type == "asks":
            return asks
        elif type == "bids":
            return bids
        else:
            return response


class BINANCEFUTURES:
    """币安币本位合约rest api"""

    def __init__(self, access_key, secret_key, instrument_id, leverage=None, position_side=None):
        """
        初始化
        :param access_key: api_key
        :param secret_key: secret_key
        :param symbol: 合约ID，例如：交割合约："ADA-USD-200925"  永续合约："ADA-USD-SWAP"
        :param leverage:开仓杠杆倍数，如不填则默认设置为20倍
        :param position_side:持仓模式，如不填则默认为单向持仓，如需双向持仓请传入"both"
        """
        self.__access_key = access_key
        self.__secret_key = secret_key
        if "SWAP" in instrument_id:
            self.__instrument_id = "{}{}_{}".format(instrument_id.split("-")[0], instrument_id.split("-")[1], "PERP")
        else:
            self.__instrument_id = "{}{}_{}".format(instrument_id.split("-")[0], instrument_id.split("-")[1], instrument_id.split("-")[2])
        self.__binance_futures = binance_futures
        self.__binance_futures.set(self.__access_key, self.__secret_key)   # 设置api
        self.position_side = position_side  # 持仓模式
        self.__leverage = leverage or 20
        if self.position_side == "both":
            # 设置所有symbol合约上的持仓模式为双向持仓模式
            self.__binance_futures.set_side_mode(dualSidePosition="true")
        else:
            # 设置所有symbol合约上的持仓模式为单向持仓模式
            self.__binance_futures.set_side_mode(dualSidePosition="false")
        # 设置指定symbol合约上的保证金模式为全仓模式
        self.__binance_futures.set_margin_mode(symbol=self.__instrument_id, marginType="CROSSED")
        self.__binance_futures.set_leverage(self.__instrument_id, self.__leverage)

    def get_single_equity(self, currency):
        """
        获取单个币种合约的权益
        :param currency: 例如 "ETC"
        :return:返回浮点数
        """
        data = self.__binance_futures.balance()
        for i in data:
            if i["asset"] == currency:
                balance = float(i["balance"])
                return balance

    def buy(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            positionSide = "LONG" if self.position_side == "both" else "BOTH"
            order_type = "LIMIT" if order_type is None else order_type  # 默认限价单
            timeInForce = "GTC" if timeInForce is None else timeInForce  # 默认成交为止，订单会一直有效，直到被成交或者取消。
            result = self.__binance_futures.order(symbol=self.__instrument_id,
                                               side="BUY",
                                               positionSide=positionSide,
                                               quantity=size,
                                               price=price,
                                               orderType=order_type,
                                               timeInForce=timeInForce)
            if "msg" in str(result):   # 如果下单失败就抛出异常，提示错误信息。
                raise SendOrderError(result["msg"])
            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                                size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['orderId'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['orderId'])
                    state = self.get_order_info(order_id=result['orderId'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['orderId'])
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def sell(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            positionSide = "LONG" if self.position_side == "both" else "BOTH"
            order_type = "LIMIT" if order_type is None else order_type  # 默认限价单
            timeInForce = "GTC" if timeInForce is None else timeInForce  # 默认成交为止，订单会一直有效，直到被成交或者取消。
            result = self.__binance_futures.order(symbol=self.__instrument_id,
                                               side="SELL",
                                               positionSide=positionSide,
                                               quantity=size,
                                               price=price,
                                               orderType=order_type,
                                               timeInForce=timeInForce)
            if "msg" in str(result):   # 如果下单失败就抛出异常，提示错误信息。
                raise SendOrderError(result["msg"])
            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                                size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['orderId'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['orderId'])
                    state = self.get_order_info(order_id=result['orderId'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['orderId'])
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def buytocover(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            positionSide = "SHORT" if self.position_side == "both" else "BOTH"
            order_type = "LIMIT" if order_type is None else order_type  # 默认限价单
            timeInForce = "GTC" if timeInForce is None else timeInForce  # 默认成交为止，订单会一直有效，直到被成交或者取消。
            result = self.__binance_futures.order(symbol=self.__instrument_id,
                                               side="BUY",
                                               positionSide=positionSide,
                                               quantity=size,
                                               price=price,
                                               orderType=order_type,
                                               timeInForce=timeInForce)
            if "msg" in str(result):   # 如果下单失败就抛出异常，提示错误信息。
                raise SendOrderError(result["msg"])
            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                                size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['orderId'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['orderId'])
                    state = self.get_order_info(order_id=result['orderId'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['orderId'])
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def sellshort(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            positionSide = "SHORT" if self.position_side == "both" else "BOTH"
            order_type = "LIMIT" if order_type is None else order_type  # 默认限价单
            timeInForce = "GTC" if timeInForce is None else timeInForce  # 默认成交为止，订单会一直有效，直到被成交或者取消。
            result = self.__binance_futures.order(symbol=self.__instrument_id,
                                               side="SELL",
                                               positionSide=positionSide,
                                               quantity=size,
                                               price=price,
                                               orderType=order_type,
                                               timeInForce=timeInForce)
            if "msg" in str(result):   # 如果下单失败就抛出异常，提示错误信息。
                raise SendOrderError(result["msg"])
            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                                size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['orderId'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['orderId'])
                    state = self.get_order_info(order_id=result['orderId'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['orderId'])
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def BUY(self, cover_short_price, cover_short_size, open_long_price, open_long_size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            result1 = self.buytocover(cover_short_price, cover_short_size, order_type)
            if "完全成交" in str(result1):
                result2 = self.buy(open_long_price, open_long_size, order_type)
                return {"平仓结果": result1, "开仓结果": result2}
            else:
                return result1
        else:   # 回测模式
            return "回测模拟下单成功！"

    def SELL(self, cover_long_price, cover_long_size, open_short_price, open_short_size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            result1 = self.sell(cover_long_price, cover_long_size, order_type)
            if "完全成交" in str(result1):
                result2 = self.sellshort(open_short_price, open_short_size, order_type)
                return {"平仓结果": result1, "开仓结果": result2}
            else:
                return result1
        else:   # 回测模式
            return "回测模拟下单成功！"


    def get_order_info(self, order_id):
        """币安币本位合约查询订单信息"""
        result = self.__binance_futures.orderStatus(symbol=self.__instrument_id, orderId=order_id)
        instrument_id = self.__instrument_id
        action = None
        if result['side'] == 'BUY' and result["positionSide"] == "BOTH":
            action = "买入"
        elif result['side'] == 'SELL' and result["positionSide"] == "BOTH":
            action = "卖出"
        elif result['side'] == 'BUY' and result["positionSide"] == "LONG":
            action = "买入开多"
        elif result['side'] == 'SELL' and result["positionSide"] == "SHORT":
            action = "卖出开空"
        elif result['side'] == 'BUY' and result["positionSide"] == "SHORT":
            action = "买入平空"
        elif result['side'] == 'SELL' and result["positionSide"] == "LONG":
            action = "卖出平多"

        if result['status'] == "FILLED":
            dict = {"交易所": "币安币本位合约", "币对": instrument_id, "方向": action, "订单状态": "完全成交",
                    "成交均价": float(result['avgPrice']),
                    "已成交数量": int(result['executedQty']),
                    "成交金额": float(result["cumBase"])}
            return dict
        elif result['status'] == "REJECTED":
            dict = {"交易所": "币安币本位合约", "币对": instrument_id, "方向": action, "订单状态": "失败"}
            return dict
        elif result['status'] == "CANCELED":
            dict = {"交易所": "币安币本位合约", "币对": instrument_id, "方向": action, "订单状态": "撤单成功",
                    "成交均价": float(result['avgPrice']),
                    "已成交数量": int(result['executedQty']),
                    "成交金额": float(result["cumBase"])}
            return dict
        elif result['status'] == "NEW":
            dict = {"交易所": "币安币本位合约", "币对": instrument_id, "方向": action, "订单状态": "等待成交"}
            return dict
        elif result['status'] == "PARTIALLY_FILLED":
            dict = {"交易所": "币安币本位合约", "币对": instrument_id, "方向": action, "订单状态": "部分成交",
                    "成交均价": float(result['avgPrice']),
                    "已成交数量": int(result['executedQty']),
                    "成交金额": float(result["cumBase"])}
            return dict
        elif result['status'] == "EXPIRED":
            dict = {"交易所": "币安币本位合约", "币对": instrument_id, "方向": action, "订单状态": "订单被交易引擎取消",
                    "成交均价": float(result['avgPrice']),
                    "已成交数量": int(result['executedQty']),
                    "成交金额": float(result["cumBase"])}
            return dict
        elif result['status'] == "PENDING_CANCEL	":
            dict = {"交易所": "币安币本位合约", "币对": instrument_id, "方向": action, "订单状态": "撤单中"}
            return dict

    def revoke_order(self, order_id):
        """币安币本位合约撤销订单"""
        receipt = self.__binance_futures.cancel(self.__instrument_id, orderId=order_id)
        if receipt['status'] == "CANCELED":
            return '【交易提醒】撤单成功'
        else:
            return '【交易提醒】撤单失败'

    def get_ticker(self):
        """币安币本位合约查询最新价"""
        response = self.__binance_futures.get_ticker(self.__instrument_id)[0]
        receipt = {'symbol': response['symbol'], 'last': response['price']}
        return receipt

    def get_kline(self, time_frame):
        """
        币安币本位合约获取k线数据
        :param time_frame: k线周期。1m， 3m， 5m， 15m， 30m， 1h， 2h， 4h， 6h， 8h， 12h， 1d， 3d， 1w， 1M
        :return:返回一个列表，包含开盘时间戳、开盘价、最高价、最低价、收盘价、成交量。
        """
        receipt = self.__binance_futures.klines(self.__instrument_id, time_frame)  # 获取历史k线数据
        for item in receipt:
            item[0] = ts_to_utc_str(int(item[0])/1000)
            item.pop(6)
            item.pop(7)
            item.pop(8)
            item.pop(6)
            item.pop(7)
            item.pop(6)
        receipt.reverse()
        return receipt

    def get_position(self, mode=None):
        """
        币安币本位合约获取持仓信息
        :return: 返回一个字典，{'direction': direction, 'amount': amount, 'price': price}
        """
        if mode == "both":
            long_amount = 0
            long_price = 0
            short_amount = 0
            short_price = 0
            receipt = self.__binance_futures.position()
            for item in receipt:
                if item["symbol"] == self.__instrument_id:
                    if item["positionSide"] == "LONG":
                        long_amount = int(item["positionAmt"])
                        long_price = float(item["entryPrice"])
                    if item["positionSide"] == "SHORT":
                        short_amount = abs(int(item["positionAmt"]))
                        short_price = float(item["entryPrice"])
            return {
                "long": {
                    "price": long_price,
                    "amount": long_amount
                },
                "short":{
                    "price": short_price,
                    "amount": short_amount
                }
            }
        else:
            result = None
            receipt = self.__binance_futures.position()
            for item in receipt:
                if item["symbol"] == self.__instrument_id and item["positionSide"] == "BOTH":
                    if item["positionAmt"] == "0":
                        direction = "none"
                    else:
                        direction = 'long' if "-" not in item["positionAmt"] else "short"
                    amount = abs(int(item['positionAmt']))
                    price = float(item["entryPrice"])
                    result = {'direction': direction, 'amount': amount, 'price': price}
            return result

    def get_contract_value(self):
        receipt = self.__binance_futures.get_contract_value(self.__instrument_id)
        return receipt

    def get_depth(self, type=None):
        """
        币安币本位合约获取深度数据
        :param type: 如不传参，返回asks和bids；只获取asks传入type="asks"；只获取"bids"传入type="bids"
        :return:返回10档深度数据
        """
        response = self.__binance_futures.depth(self.__instrument_id)
        asks_list = response["asks"]
        bids_list = response["bids"]
        asks = []
        bids = []
        for i in asks_list:
            asks.append(float(i[0]))
        for j in bids_list:
            bids.append(float(j[0]))
        if type == "asks":
            return asks
        elif type == "bids":
            return bids
        else:
            return response

class BINANCESWAP:
    """币安USDT合约rest api"""

    def __init__(self, access_key, secret_key, instrument_id, leverage=None, position_side=None):
        """
        初始化
        :param access_key: api_key
        :param secret_key: secret_key
        :param symbol: 合约ID,例如'BTC-USDT-SWAP'
        :param leverage:杠杆倍数，如不填则默认设置为20倍杠杆
        :param leverage:持仓模式，如不填则默认设置为单向持仓，如需双向持仓请传入参数"both"
        """
        self.__access_key = access_key
        self.__secret_key = secret_key
        self.__instrument_id = "{}{}".format(instrument_id.split("-")[0], instrument_id.split("-")[1])
        self.__binance_swap = binance_swap
        self.__binance_swap.set(self.__access_key, self.__secret_key)   # 设置api
        self.__leverage = leverage or 20
        self.position_side = position_side
        if self.position_side == "both":
            self.__binance_swap.set_side_mode(dualSidePosition="true")
        else:
            # 设置所有symbol合约上的持仓模式为单向持仓模式
            self.__binance_swap.set_side_mode(dualSidePosition="false")
        # 设置指定symbol合约上的保证金模式为全仓模式
        self.__binance_swap.set_margin_mode(symbol=self.__instrument_id, marginType="CROSSED")
        self.__binance_swap.set_leverage(self.__instrument_id, self.__leverage)  # 设置杠杆倍数

    def get_single_equity(self, currency):
        """
        获取合约的权益
        :param currency: 例如 "USDT"或"BNB"
        :return:返回浮点数
        """
        data = self.__binance_swap.balance()
        for i in data:
            if i["asset"] == currency:
                balance = float(i["balance"])
                return balance

    def buy(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            positionSide = "LONG" if self.position_side == "both" else "BOTH"
            order_type = "LIMIT" if order_type is None else order_type  # 默认限价单
            timeInForce = "GTC" if timeInForce is None else timeInForce  # 默认成交为止，订单会一直有效，直到被成交或者取消。
            result = self.__binance_swap.order(symbol=self.__instrument_id,
                                               side="BUY",
                                               positionSide=positionSide,
                                               quantity=size,
                                               price=price,
                                               orderType=order_type,
                                               timeInForce=timeInForce)
            if "msg" in str(result):   # 如果下单失败就抛出异常，提示错误信息。
                raise SendOrderError(result["msg"])
            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                                size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['orderId'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['orderId'])
                    state = self.get_order_info(order_id=result['orderId'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def sell(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            positionSide = "LONG" if self.position_side == "both" else "BOTH"
            order_type = "LIMIT" if order_type is None else order_type  # 默认限价单
            timeInForce = "GTC" if timeInForce is None else timeInForce  # 默认成交为止，订单会一直有效，直到被成交或者取消。
            result = self.__binance_swap.order(symbol=self.__instrument_id,
                                               side=positionSide,
                                               positionSide="BOTH",
                                               quantity=size,
                                               price=price,
                                               orderType=order_type,
                                               timeInForce=timeInForce)
            if "msg" in str(result):   # 如果下单失败就抛出异常，提示错误信息。
                raise SendOrderError(result["msg"])
            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                                size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['orderId'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['orderId'])
                    state = self.get_order_info(order_id=result['orderId'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def buytocover(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            positionSide = "SHORT" if self.position_side == "both" else "BOTH"
            order_type = "LIMIT" if order_type is None else order_type  # 默认限价单
            timeInForce = "GTC" if timeInForce is None else timeInForce  # 默认成交为止，订单会一直有效，直到被成交或者取消。
            result = self.__binance_swap.order(symbol=self.__instrument_id,
                                               side="BUY",
                                               positionSide=positionSide,
                                               quantity=size,
                                               price=price,
                                               orderType=order_type,
                                               timeInForce=timeInForce)
            if "msg" in str(result):   # 如果下单失败就抛出异常，提示错误信息。
                raise SendOrderError(result["msg"])
            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                                size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['orderId'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['orderId'])
                    state = self.get_order_info(order_id=result['orderId'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def sellshort(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            positionSide = "SHORT" if self.position_side == "both" else "BOTH"
            order_type = "LIMIT" if order_type is None else order_type  # 默认限价单
            timeInForce = "GTC" if timeInForce is None else timeInForce  # 默认成交为止，订单会一直有效，直到被成交或者取消。
            result = self.__binance_swap.order(symbol=self.__instrument_id,
                                               side="SELL",
                                               positionSide="BOTH",
                                               quantity=size,
                                               price=price,
                                               orderType=order_type,
                                               timeInForce=timeInForce)
            if "msg" in str(result):   # 如果下单失败就抛出异常，提示错误信息。
                raise SendOrderError(result["msg"])
            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
            # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id=result['orderId'])
                            state = self.get_order_info(order_id=result['orderId'])
                            if state['订单状态'] == "撤单成功":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                                size - state["已成交数量"])
                        except:
                            order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info(order_id=result['orderId'])
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order), size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id=result['orderId'])
                        state = self.get_order_info(order_id=result['orderId'])
                        if state['订单状态'] == "撤单成功":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                        if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id=result['orderId'])
                    state = self.get_order_info(order_id=result['orderId'])
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info(order_id=result['orderId'])  # 下单后查询一次订单状态
                    if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def BUY(self, cover_short_price, cover_short_size, open_long_price, open_long_size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            result1 = self.buytocover(cover_short_price, cover_short_size, order_type)
            if "完全成交" in str(result1):
                result2 = self.buy(open_long_price, open_long_size, order_type)
                return {"平仓结果": result1, "开仓结果": result2}
            else:
                return result1
        else:   # 回测模式
            return "回测模拟下单成功！"

    def SELL(self, cover_long_price, cover_long_size, open_short_price, open_short_size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            result1 = self.sell(cover_long_price, cover_long_size, order_type)
            if "完全成交" in str(result1):
                result2 = self.sellshort(open_short_price, open_short_size, order_type)
                return {"平仓结果": result1, "开仓结果": result2}
            else:
                return result1
        else:   # 回测模式
            return "回测模拟下单成功！"


    def get_order_info(self, order_id):
        """币安USDT合约查询订单信息"""
        result = self.__binance_swap.orderStatus(symbol=self.__instrument_id, orderId=order_id)
        instrument_id = self.__instrument_id
        action = None
        if result['side'] == 'BUY' and result["positionSide"] == "BOTH":
            action = "买入"
        elif result['side'] == 'SELL' and result["positionSide"] == "BOTH":
            action = "卖出"
        elif result['side'] == 'BUY' and result["positionSide"] == "LONG":
            action = "买入开多"
        elif result['side'] == 'SELL' and result["positionSide"] == "SHORT":
            action = "卖出开空"
        elif result['side'] == 'BUY' and result["positionSide"] == "SHORT":
            action = "买入平空"
        elif result['side'] == 'SELL' and result["positionSide"] == "LONG":
            action = "卖出平多"

        if result['status'] == "FILLED":
            dict = {"交易所": "币安USDT合约", "币对": instrument_id, "方向": action, "订单状态": "完全成交",
                    "成交均价": float(result['avgPrice']),
                    "已成交数量": float(result['executedQty']),
                    "成交金额": float(result["cumQuote"])}
            return dict
        elif result['status'] == "REJECTED":
            dict = {"交易所": "币安USDT合约", "币对": instrument_id, "方向": action, "订单状态": "失败"}
            return dict
        elif result['status'] == "CANCELED":
            dict = {"交易所": "币安USDT合约", "币对": instrument_id, "方向": action, "订单状态": "撤单成功",
                    "成交均价": float(result['avgPrice']),
                    "已成交数量": float(result['executedQty']),
                    "成交金额": float(result["cumQuote"])}
            return dict
        elif result['status'] == "NEW":
            dict = {"交易所": "币安USDT合约", "币对": instrument_id, "方向": action, "订单状态": "等待成交"}
            return dict
        elif result['status'] == "PARTIALLY_FILLED":
            dict = {"交易所": "币安USDT合约", "币对": instrument_id, "方向": action, "订单状态": "部分成交",
                    "成交均价": float(result['avgPrice']),
                    "已成交数量": float(result['executedQty']),
                    "成交金额": float(result["cumQuote"])}
            return dict
        elif result['status'] == "EXPIRED":
            dict = {"交易所": "币安USDT合约", "币对": instrument_id, "方向": action, "订单状态": "订单被交易引擎取消",
                    "成交均价": float(result['avgPrice']),
                    "已成交数量": float(result['executedQty']),
                    "成交金额": float(result["cumQuote"])}
            return dict
        elif result['status'] == "PENDING_CANCEL	":
            dict = {"交易所": "币安USDT合约", "币对": instrument_id, "方向": action, "订单状态": "撤单中"}
            return dict

    def revoke_order(self, order_id):
        """币安USDT合约撤销订单"""
        receipt = self.__binance_swap.cancel(self.__instrument_id, orderId=order_id)
        if receipt['status'] == "CANCELED":
            return '【交易提醒】撤单成功'
        else:
            return '【交易提醒】撤单失败'

    def get_ticker(self):
        """币安USDT合约查询最新价"""
        response = self.__binance_swap.get_ticker(self.__instrument_id)
        receipt = {'symbol': response['symbol'], 'last': response['price']}
        return receipt

    def get_kline(self, time_frame):
        """
        币安USDT合约获取k线数据
        :param time_frame: k线周期。1m， 3m， 5m， 15m， 30m， 1h， 2h， 4h， 6h， 8h， 12h， 1d， 3d， 1w， 1M
        :return:返回一个列表，包含开盘时间戳、开盘价、最高价、最低价、收盘价、成交量。
        """
        receipt = self.__binance_swap.klines(self.__instrument_id, time_frame)  # 获取历史k线数据
        for item in receipt:
            item[0] = ts_to_utc_str(int(item[0])/1000)
            item.pop(6)
            item.pop(7)
            item.pop(8)
            item.pop(6)
            item.pop(7)
            item.pop(6)
        receipt.reverse()
        return receipt

    def get_position(self, mode=None):
        """
        币安USDT合约获取持仓信息
        :return: 返回一个字典，{'direction': direction, 'amount': amount, 'price': price}
        """
        if mode == "both":
            long_amount = 0
            long_price = 0
            short_amount = 0
            short_price = 0
            receipt = self.__binance_swap.position()
            for item in receipt:
                if item["symbol"] == self.__instrument_id:
                    if item["positionSide"] == "LONG":
                        long_amount = float(item["positionAmt"])
                        long_price = float(item["entryPrice"])
                    if item["positionSide"] == "SHORT":
                        short_amount = abs(float(item["positionAmt"]))
                        short_price = float(item["entryPrice"])
            return {
                "long": {
                    "price": long_price,
                    "amount": long_amount
                },
                "short":{
                    "price": short_price,
                    "amount": short_amount
                }
            }
        else:
            result = None
            receipt = self.__binance_swap.position()
            for item in receipt:
                if item["symbol"] == self.__instrument_id:
                    if item["positionAmt"] == "0.000":
                        direction = "none"
                    else:
                        direction = 'long' if "-" not in item["positionAmt"] else "short"
                    amount = abs(float(item['positionAmt']))
                    price = float(item["entryPrice"])
                    result = {'direction': direction, 'amount': amount, 'price': price}
            return result

    def get_contract_value(self):
        receipt = self.__binance_swap.get_contract_value(self.__instrument_id)
        return receipt

    def get_depth(self, type=None):
        """
        币安USDT合约获取深度数据
        :param type: 如不传参，返回asks和bids；只获取asks传入type="asks"；只获取"bids"传入type="bids"
        :return:返回10档深度数据
        """
        response = self.__binance_swap.depth(self.__instrument_id)
        asks_list = response["asks"]
        bids_list = response["bids"]
        asks = []
        bids = []
        for i in asks_list:
            asks.append(float(i[0]))
        for j in bids_list:
            bids.append(float(j[0]))
        if type == "asks":
            return asks
        elif type == "bids":
            return bids
        else:
            return response

class BITMEX:

    def __init__(self, access_key, secret_key, instrument_id, leverage=None, testing=None):
        """
        BITMEX rest api
        :param access_key: api key
        :param secret_key: secret key
        :param instrument_id: 合约id，例如："XBTUSD"
        :param testing:是否是测试账户，默认为False
        :param leverage:开仓杠杆倍数，如不填则默认设置为20倍
        """
        self.__access_key = access_key
        self.__secret_key = secret_key
        self.__instrument_id = instrument_id
        self.__testing = False or testing
        self.__bitmex = Bitmex(self.__access_key, self.__secret_key, testing=self.__testing)
        self.__leverage = leverage or 20
        self.__bitmex.set_leverage(self.__instrument_id, leverage=self.__leverage)

    def get_single_equity(self, currency=None):
        """
        获取合约的权益
        :param currency: 默认为"XBt",BITMEX所有的交易是用XBT来结算的
        :return:返回浮点数
        """
        currency = "XBt"
        data = self.__bitmex.get_wallet(currency=currency)
        XBT = data["prevAmount"] * 0.00000001
        return XBT

    def get_depth(self, type=None, depth=None):
        """
        BITMEX获取深度数据
        :param type:如不传参，返回asks和bids；只获取asks传入type="asks"；只获取"bids"传入type="bids"
        :param depth:返回深度档位数量，默认10档
        :return:
        """
        depth = depth or 10
        response = self.__bitmex.get_orderbook(self.__instrument_id, depth=depth)
        asks_list = []   # 卖盘
        bids_list = []   # 买盘
        for i in response:
            if i['side'] == "Sell":
                asks_list.append(i['price'])
            elif i['side'] == "Buy":
                bids_list.append(i['price'])
        result = {"asks": asks_list, "bids": bids_list}
        if type == "asks":
            return asks_list
        elif type == "bids":
            return bids_list
        else:
            return result

    def get_ticker(self):
        """获取最新成交价"""
        receipt = self.__bitmex.get_trade(symbol=self.__instrument_id, reverse=True, count=10)[0]
        last = receipt["price"]
        return {"last": last}

    def get_position(self):
        try:
            result = self.__bitmex.get_positions(symbol=self.__instrument_id)[0]
            if result["currentQty"] > 0:
                dict = {'direction': 'long', 'amount': result["currentQty"],
                        'price': result["avgCostPrice"]}
                return dict
            elif result["currentQty"] < 0:
                dict = {'direction': 'short', 'amount': abs(result['currentQty']),
                        'price': result['avgCostPrice']}
                return dict
            else:
                dict = {'direction': 'none', 'amount': 0, 'price': 0.0}
                return dict
        except Exception as e:
            raise GetPositionError(e)

    def get_kline(self, time_frame, count=None):
        """
        获取k线数据
        :param time_frame: k线周期
        :param count: 返回的k线数量，默认为200条
        :return:
        """
        count = count or 200
        records = []
        response = self.__bitmex.get_bucket_trades(binSize=time_frame, partial=False, symbol=self.__instrument_id,
                                                   columns="timestamp, open, high, low, close, volume", count=count,
                                                   reverse=True)
        for i in response:
            records.append([i['timestamp'], i['open'], i['high'], i['low'], i['close'], i['volume']])
        return records

    def revoke_order(self, order_id):
        receipt = self.__bitmex.cancel_order(order_id)
        return receipt

    def get_order_info(self):
        result = self.__bitmex.get_orders(symbol=self.__instrument_id, count=1, reverse=True)[0]
        action = "买入" if result['side'] == "Buy" else "卖出"
        symbol = result["symbol"]
        price = result["avgPx"]
        amount = result["cumQty"]
        order_status = result['ordStatus']
        if order_status == "Filled":
            dict = {"交易所": "BITMEX", "合约ID": symbol, "方向": action,
                    "订单状态": "完全成交", "成交均价": price, "已成交数量": amount}
            return dict
        elif order_status == "Rejected":
            dict = {"交易所": "BITMEX", "合约ID": symbol, "方向": action, "订单状态": "失败"}
            return dict
        elif order_status == "Canceled":
            dict = {"交易所": "BITMEX", "合约ID": symbol, "方向": action, "订单状态": "撤单成功",
                    "成交均价": price, "已成交数量": amount}
            return dict
        elif order_status == "New":
            dict = {"交易所": "BITMEX", "合约ID": symbol, "方向": action, "订单状态": "等待成交"}
            return dict
        elif order_status == "PartiallyFilled":
            dict = {"交易所": "BITMEX", "合约ID": symbol, "方向": action, "订单状态": "部分成交",
                    "成交均价": price, "已成交数量": amount}
            return dict


    def buy(self, price, size, order_type=None, timeInForce=None):
        """
        买入开多
        :param price: 价格
        :param amount: 数量
        :param order_type: Market, Limit, Stop, StopLimit, MarketIfTouched, LimitIfTouched, Pegged，默认是"Limit"
        :param timeInForce:Day, GoodTillCancel, ImmediateOrCancel, FillOrKill, 默认是"GoodTillCancel"
        :return:
        """
        if config.backtest != "enabled":  # 实盘模式
            order_type = order_type or "Limit"
            timeInForce = timeInForce or "GoodTillCancel"
            result = self.__bitmex.create_order(symbol=self.__instrument_id, side="Buy", price=price, orderQty=size,
                                                ordType=order_type, timeInForce=timeInForce)
            try:
                raise SendOrderError(msg=result['error']['message'])
            except:
                order_id = result["orderID"]
                order_info = self.get_order_info()  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
                # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:  # 如果撤单失败，则订单可能在此期间已完全成交或部分成交
                            self.revoke_order(order_id)
                            state = self.get_order_info()
                            if state['订单状态'] == "撤单成功":  # 已完全成交时，以原下单数量重发；部分成交时，重发委托数量为原下单数量减去已成交数量
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                                size - state["已成交数量"])
                        except:  # 撤单失败时，说明订单已完全成交
                            order_info = self.get_order_info()  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id)
                            state = self.get_order_info()
                            if state['订单状态'] == "撤单成功":
                                return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                                size - state["已成交数量"])
                        except:  # 撤单失败时，说明订单已完全成交，再查询一次订单状态，如果已完全成交，返回下单结果
                            order_info = self.get_order_info()  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info()
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id)
                        state = self.get_order_info()
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info()  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id)
                        state = self.get_order_info()
                        if state['订单状态'] == "撤单成功":
                            return self.buy(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info()  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id)
                    state = self.get_order_info()
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info()  # 再查询一次订单状态
                    if order_info["订单状态"] == "完全成交":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def sell(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            order_type = order_type or "Limit"
            timeInForce = timeInForce or "GoodTillCancel"
            result = self.__bitmex.create_order(symbol=self.__instrument_id, side="Sell", price=price, orderQty=size,
                                                ordType=order_type, timeInForce=timeInForce)
            try:
                raise SendOrderError(msg=result['error']['message'])
            except:
                order_id = result["orderID"]
                order_info = self.get_order_info()  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
                # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:  # 如果撤单失败，则订单可能在此期间已完全成交或部分成交
                            self.revoke_order(order_id)
                            state = self.get_order_info()
                            if state['订单状态'] == "撤单成功":  # 已完全成交时，以原下单数量重发；部分成交时，重发委托数量为原下单数量减去已成交数量
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                                size + state["已成交数量"])
                        except:  # 撤单失败时，说明订单已完全成交
                            order_info = self.get_order_info()  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id)
                            state = self.get_order_info()
                            if state['订单状态'] == "撤单成功":
                                return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                                size + state["已成交数量"])
                        except:  # 撤单失败时，说明订单已完全成交，再查询一次订单状态，如果已完全成交，返回下单结果
                            order_info = self.get_order_info()  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info()
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id)
                        state = self.get_order_info()
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                            size + state["已成交数量"])
                    except:
                        order_info = self.get_order_info()  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id)
                        state = self.get_order_info()
                        if state['订单状态'] == "撤单成功":
                            return self.sell(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                            size + state["已成交数量"])
                    except:
                        order_info = self.get_order_info()  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id)
                    state = self.get_order_info()
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info()  # 再查询一次订单状态
                    if order_info["订单状态"] == "完全成交":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def sellshort(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            order_type = order_type or "Limit"
            timeInForce = timeInForce or "GoodTillCancel"
            result = self.__bitmex.create_order(symbol=self.__instrument_id, side="Sell", price=price, orderQty=size,
                                                ordType=order_type, timeInForce=timeInForce)
            try:
                raise SendOrderError(msg=result['error']['message'])
            except:
                order_id = result["orderID"]
                order_info = self.get_order_info()  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
                # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:  # 如果撤单失败，则订单可能在此期间已完全成交或部分成交
                            self.revoke_order(order_id)
                            state = self.get_order_info()
                            if state['订单状态'] == "撤单成功":  # 已完全成交时，以原下单数量重发；部分成交时，重发委托数量为原下单数量减去已成交数量
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                                size + state["已成交数量"])
                        except:  # 撤单失败时，说明订单已完全成交
                            order_info = self.get_order_info()  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) <= price * (1 - config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id)
                            state = self.get_order_info()
                            if state['订单状态'] == "撤单成功":
                                return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                                size + state["已成交数量"])
                        except:  # 撤单失败时，说明订单已完全成交，再查询一次订单状态，如果已完全成交，返回下单结果
                            order_info = self.get_order_info()  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info()
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id)
                        state = self.get_order_info()
                        if state['订单状态'] == "撤单成功":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                            size + state["已成交数量"])
                    except:
                        order_info = self.get_order_info()  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id)
                        state = self.get_order_info()
                        if state['订单状态'] == "撤单成功":
                            return self.sellshort(float(self.get_ticker()['last']) * (1 - config.reissue_order),
                                            size + state["已成交数量"])
                    except:
                        order_info = self.get_order_info()  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id)
                    state = self.get_order_info()
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info()  # 再查询一次订单状态
                    if order_info["订单状态"] == "完全成交":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def buytocover(self, price, size, order_type=None, timeInForce=None):
        if config.backtest != "enabled":  # 实盘模式
            order_type = order_type or "Limit"
            timeInForce = timeInForce or "GoodTillCancel"
            result = self.__bitmex.create_order(symbol=self.__instrument_id, side="Buy", price=price, orderQty=size,
                                                ordType=order_type, timeInForce=timeInForce)
            try:
                raise SendOrderError(msg=result['error']['message'])
            except:
                order_id = result["orderID"]
                order_info = self.get_order_info()  # 下单后查询一次订单状态
            if order_info["订单状态"] == "完全成交" or order_info["订单状态"] == "失败 ":  # 如果订单状态为"完全成交"或者"失败"，返回结果
                return {"【交易提醒】下单结果": order_info}
                # 如果订单状态不是"完全成交"或者"失败"
            if config.price_cancellation == "true":  # 选择了价格撤单时，如果最新价超过委托价一定幅度，撤单重发，返回下单结果
                if order_info["订单状态"] == "等待成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:  # 如果撤单失败，则订单可能在此期间已完全成交或部分成交
                            self.revoke_order(order_id)
                            state = self.get_order_info()
                            if state['订单状态'] == "撤单成功":  # 已完全成交时，以原下单数量重发；部分成交时，重发委托数量为原下单数量减去已成交数量
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                                size - state["已成交数量"])
                        except:  # 撤单失败时，说明订单已完全成交
                            order_info = self.get_order_info()  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    if float(self.get_ticker()['last']) >= price * (1 + config.price_cancellation_amplitude):
                        try:
                            self.revoke_order(order_id)
                            state = self.get_order_info()
                            if state['订单状态'] == "撤单成功":
                                return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                                size - state["已成交数量"])
                        except:  # 撤单失败时，说明订单已完全成交，再查询一次订单状态，如果已完全成交，返回下单结果
                            order_info = self.get_order_info()  # 再查询一次订单状态
                            if order_info["订单状态"] == "完全成交":
                                return {"【交易提醒】下单结果": order_info}
            if config.time_cancellation == "true":  # 选择了时间撤单时，如果委托单发出多少秒后不成交，撤单重发，直至完全成交，返回成交结果
                time.sleep(config.time_cancellation_seconds)
                order_info = self.get_order_info()
                if order_info["订单状态"] == "等待成交":
                    try:
                        self.revoke_order(order_id)
                        state = self.get_order_info()
                        if state['订单状态'] == "撤单成功":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info()  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
                if order_info["订单状态"] == "部分成交":
                    try:
                        self.revoke_order(order_id)
                        state = self.get_order_info()
                        if state['订单状态'] == "撤单成功":
                            return self.buytocover(float(self.get_ticker()['last']) * (1 + config.reissue_order),
                                            size - state["已成交数量"])
                    except:
                        order_info = self.get_order_info()  # 再查询一次订单状态
                        if order_info["订单状态"] == "完全成交":
                            return {"【交易提醒】下单结果": order_info}
            if config.automatic_cancellation == "true":
                # 如果订单未完全成交，且未设置价格撤单和时间撤单，且设置了自动撤单，就自动撤单并返回下单结果与撤单结果
                try:
                    self.revoke_order(order_id)
                    state = self.get_order_info()
                    return {"【交易提醒】下单结果": state}
                except:
                    order_info = self.get_order_info()  # 再查询一次订单状态
                    if order_info["订单状态"] == "完全成交":
                        return {"【交易提醒】下单结果": order_info}
            else:  # 未启用交易助手时，下单并查询订单状态后直接返回下单结果
                return {"【交易提醒】下单结果": order_info}
        else:  # 回测模式
            return "回测模拟下单成功！"

    def BUY(self, cover_short_price, cover_short_size, open_long_price, open_long_size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            result1 = self.buytocover(cover_short_price, cover_short_size, order_type)
            if "完全成交" in str(result1):
                result2 = self.buy(open_long_price, open_long_size, order_type)
                return {"平仓结果": result1, "开仓结果": result2}
            else:
                return result1
        else:   # 回测模式
            return "回测模拟下单成功！"

    def SELL(self, cover_long_price, cover_long_size, open_short_price, open_short_size, order_type=None):
        if config.backtest != "enabled":    # 实盘模式
            result1 = self.sell(cover_long_price, cover_long_size, order_type)
            if "完全成交" in str(result1):
                result2 = self.sellshort(open_short_price, open_short_size, order_type)
                return {"平仓结果": result1, "开仓结果": result2}
            else:
                return result1