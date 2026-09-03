from __future__ import annotations

import math

import numpy as np

from .ai_engine import out_of_sample_probabilities
from .indicators import calculate_indicators


def run_backtest(candles: list[dict], strategy: str, initial_cash: float, fee_rate: float = 0.001) -> dict:
    if initial_cash <= 0: raise ValueError("初始资金必须大于 0")
    df=calculate_indicators(candles)
    if len(df)<80:raise ValueError("回测至少需要 80 根 K线")
    if strategy in {"ai","ai_technical"}:
        df,up_probability=out_of_sample_probabilities(candles);df["ai_up"]=up_probability
    signals=[]
    for _,row in df.iterrows():
        if strategy=="ma": active=bool(row.get("ma5",np.nan)>row.get("ma20",np.nan))
        elif strategy=="macd":active=bool(row.get("macd",np.nan)>row.get("macd_signal",np.nan))
        elif strategy=="rsi":active=True if row.get("rsi",50)<35 else False if row.get("rsi",50)>65 else None
        elif strategy=="ai":active=bool(row.get("ai_up",np.nan)>0.55) if not np.isnan(row.get("ai_up",np.nan)) else None
        elif strategy=="ai_technical":active=bool(row.get("ai_up",np.nan)>.55 and row.get("macd",0)>row.get("macd_signal",0) and row["close"]>row.get("ma20",math.inf)) if not np.isnan(row.get("ai_up",np.nan)) else None
        else:raise ValueError("未知策略")
        signals.append(active)
    cash=float(initial_cash);quantity=0.0;entry_cost=0.0;trades=[];curve=[];peak=initial_cash;max_drawdown=0.0
    for (_,row),signal in zip(df.iterrows(),signals):
        price=float(row["close"])
        if signal is True and quantity==0 and cash>0:
            quantity=cash/(price*(1+fee_rate));cost=quantity*price;fee=cost*fee_rate;cash-=cost+fee;entry_cost=cost+fee
            trades.append({"side":"BUY","timestamp":row["timestamp"],"price":price,"quantity":quantity,"fee":fee})
        elif signal is False and quantity>0:
            gross=quantity*price;fee=gross*fee_rate;cash+=gross-fee;pnl=(gross-fee)-entry_cost
            trades.append({"side":"SELL","timestamp":row["timestamp"],"price":price,"quantity":quantity,"fee":fee,"pnl":pnl});quantity=0;entry_cost=0
        equity=cash+quantity*price;peak=max(peak,equity);max_drawdown=max(max_drawdown,(peak-equity)/peak if peak else 0)
        curve.append({"timestamp":row["timestamp"],"equity":round(equity,2)})
    if quantity>0:
        price=float(df.iloc[-1]["close"]);gross=quantity*price;fee=gross*fee_rate;cash+=gross-fee;pnl=(gross-fee)-entry_cost
        trades.append({"side":"SELL","timestamp":df.iloc[-1]["timestamp"],"price":price,"quantity":quantity,"fee":fee,"pnl":pnl});quantity=0
        curve[-1]["equity"]=round(cash,2)
    closed=[t for t in trades if t["side"]=="SELL"];wins=[t for t in closed if t["pnl"]>0];losses=[t for t in closed if t["pnl"]<=0]
    gross_profit=sum(t["pnl"] for t in wins);gross_loss=abs(sum(t["pnl"] for t in losses))
    return {"strategy":strategy,"initial_cash":round(initial_cash,2),"final_cash":round(cash,2),
            "return_percent":round((cash/initial_cash-1)*100,2),"max_drawdown_percent":round(max_drawdown*100,2),
            "win_rate_percent":round(len(wins)/len(closed)*100,2) if closed else 0,"trade_count":len(closed),
            "winning_trades":len(wins),"losing_trades":len(losses),"profit_loss_ratio":round(gross_profit/gross_loss,2) if gross_loss else (None if not gross_profit else 999),
            "equity_curve":curve,"trades":trades,"data_start":df.iloc[0]["timestamp"],"data_end":df.iloc[-1]["timestamp"],
            "notice":"历史回测包含手续费，不代表未来收益。AI 策略只使用滚动样本外预测。"}

