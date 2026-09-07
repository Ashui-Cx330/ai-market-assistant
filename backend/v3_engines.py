from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import floor

import numpy as np
import pandas as pd

from .ai_engine import feature_frame
from .horizons import INTERVAL_MINUTES


def _number(value, digits=6):
    return None if value is None or not np.isfinite(value) else round(float(value), digits)


def _percentile(series: pd.Series, value: float) -> float:
    clean = series.replace([np.inf, -np.inf], np.nan).dropna()
    return float((clean <= value).mean()) if len(clean) else .5


class CapitalFlowEngine:
    """Causal OHLCV money-flow proxy, optionally augmented with real derivatives data."""

    def analyze(self, frame: pd.DataFrame, derivatives: dict | None = None) -> dict:
        typical = (frame["high"] + frame["low"] + frame["close"]) / 3
        turnover = frame["amount"].where(frame["amount"] > 0, typical * frame["volume"])
        signed = np.sign(frame["close"].diff()).fillna(0) * turnover
        window = min(32, max(8, len(frame) // 20))
        recent = signed.iloc[-window:]
        prior = signed.iloc[-2 * window:-window]
        gross = turnover.iloc[-window:].abs().sum()
        net = recent.sum()
        ratio = float(net / gross) if gross else 0.0
        prior_ratio = float(prior.sum() / turnover.iloc[-2 * window:-window].abs().sum()) if len(prior) and turnover.iloc[-2 * window:-window].abs().sum() else 0.0
        acceleration = ratio - prior_ratio
        persistence = float((np.sign(recent) == np.sign(net)).mean()) if net else .5
        price_momentum = float(frame["close"].iloc[-1] / frame["close"].iloc[-window] - 1)
        divergence = "BEARISH_DIVERGENCE" if price_momentum > 0 and ratio < 0 else "BULLISH_DIVERGENCE" if price_momentum < 0 and ratio > 0 else "CONFIRMED"
        direction = "INFLOW" if ratio > .02 else "OUTFLOW" if ratio < -.02 else "NEUTRAL"
        result = {
            "status": "AVAILABLE", "source": "real OHLCV money-flow proxy", "is_exchange_reported_net_flow": False,
            "net_flow_proxy": _number(net, 2), "gross_turnover": _number(gross, 2), "net_flow_ratio": _number(ratio, 4),
            "flow_momentum": _number(ratio - prior_ratio / 2, 4), "flow_acceleration": _number(acceleration, 4),
            "flow_persistence": _number(persistence, 4), "direction": direction, "price_flow_relation": divergence,
            "active_buy_proxy": _number(recent.clip(lower=0).sum(), 2), "active_sell_proxy": _number(abs(recent.clip(upper=0).sum()), 2),
            "derivatives": derivatives or {"status": "NOT_APPLICABLE_OR_NO_DATA"},
        }
        if derivatives and derivatives.get("status") == "AVAILABLE":
            oi_change = derivatives.get("open_interest_change")
            if oi_change is not None:
                result["price_oi_relation"] = ("PRICE_UP_OI_UP" if price_momentum > 0 and oi_change > 0 else
                                                "PRICE_UP_OI_DOWN" if price_momentum > 0 else
                                                "PRICE_DOWN_OI_UP" if oi_change > 0 else "PRICE_DOWN_OI_DOWN")
        return result


class MarketRegimeEngine:
    def analyze(self, frame: pd.DataFrame, flow: dict, coverage: float, external_context: dict | None = None) -> dict:
        close = frame["close"]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        slope = float(close.rolling(20).mean().pct_change(5).iloc[-1])
        vol = float(frame["return_1"].rolling(20).std().iloc[-1])
        vol_rank = _percentile(frame["return_1"].rolling(20).std().iloc[:-1], vol)
        volume_ratio = float(frame["volume"].iloc[-20:].mean() / max(frame["volume"].iloc[-80:-20].mean(), 1e-12))
        trend_score = float(np.tanh(slope / max(vol, 1e-6)) * .6 + np.sign(close.iloc[-1] - ma60) * .4)
        if vol_rank >= .9 and frame["return_5"].iloc[-1] < -2 * max(vol, 1e-6): primary = "PANIC"
        elif vol_rank >= .9 and frame["return_5"].iloc[-1] > 2 * max(vol, 1e-6): primary = "EUPHORIA"
        elif vol_rank >= .8: primary = "HIGH_VOLATILITY"
        elif vol_rank <= .2: primary = "LOW_VOLATILITY"
        elif trend_score > .45: primary = "BULL_TREND"
        elif trend_score < -.45: primary = "BEAR_TREND"
        elif abs(trend_score) < .18: primary = "SIDEWAYS"
        else: primary = "TRANSITION"
        external_context=external_context or {};macro=external_context.get("macro",{});news=external_context.get("news",{})
        macro_delta={"POSITIVE":.15,"NEGATIVE":-.15}.get(macro.get("signal"),0)
        news_delta=float(np.clip(news.get("sentiment_score") or 0,-1,1))*.08
        combined=trend_score+.25*np.sign(flow["net_flow_ratio"])+macro_delta+news_delta
        risk_mode = "RISK_ON" if combined > .25 else "RISK_OFF" if combined < -.25 else "NEUTRAL"
        liquidity = "IMPROVING" if volume_ratio > 1.15 else "TIGHTENING" if volume_ratio < .8 else "NEUTRAL"
        available_external=[name for name in ("macro","news") if external_context.get(name,{}).get("status") in {"AVAILABLE","PARTIAL_DATA"}]
        unavailable_external=[name for name in ("macro","news","event") if external_context.get(name,{}).get("status") not in {"AVAILABLE","PARTIAL_DATA"}]
        return {"status": "AVAILABLE", "primary": primary, "risk_mode": risk_mode, "liquidity": liquidity,
                "trend": "UP" if trend_score > .2 else "DOWN" if trend_score < -.2 else "SIDEWAYS",
                "volatility": "HIGH" if vol_rank > .75 else "LOW" if vol_rank < .25 else "MEDIUM",
                "volatility_percentile": _number(vol_rank, 4), "trend_score": _number(trend_score, 4),
                "volume_ratio": _number(volume_ratio, 4), "feature_coverage": coverage,
                "combined_context_score":_number(combined,4),
                "inputs": ["price trend", "realized volatility", "real volume", "flow proxy", "price-volume sentiment"]+available_external,
                "unavailable_inputs": ["market breadth"]+unavailable_external}


class MarketStructureEngine:
    def analyze(self, frame: pd.DataFrame) -> dict:
        lookback = min(160, len(frame))
        data = frame.iloc[-lookback:]
        highs = data["high"][(data["high"] == data["high"].rolling(7, center=True).max())].dropna()
        lows = data["low"][(data["low"] == data["low"].rolling(7, center=True).min())].dropna()
        high_state = "HIGHER_HIGH" if len(highs) >= 2 and highs.iloc[-1] > highs.iloc[-2] else "LOWER_HIGH"
        low_state = "HIGHER_LOW" if len(lows) >= 2 and lows.iloc[-1] > lows.iloc[-2] else "LOWER_LOW"
        current = float(data["close"].iloc[-1]); prior_high = float(data["high"].iloc[:-1].tail(40).max()); prior_low = float(data["low"].iloc[:-1].tail(40).min())
        volume_confirm = data["volume"].iloc[-1] > data["volume"].tail(30).median() * 1.25
        atr = max(float(data["atr"].iloc[-1]), current * .001)
        recent_break_high = float(data["high"].iloc[-8:-1].max())
        recent_break_low = float(data["low"].iloc[-8:-1].min())
        retest_high = abs(current-prior_high) <= .35*atr and float(data["high"].iloc[-8:].max()) > prior_high
        retest_low = abs(current-prior_low) <= .35*atr and float(data["low"].iloc[-8:].min()) < prior_low
        range_width = (prior_high-prior_low)/max(current,1e-12)
        obv_slope = float(data["obv"].diff().tail(20).mean())
        price_slope = float(data["close"].pct_change().tail(20).mean())
        if current > prior_high: event = "BREAKOUT" if volume_confirm else "FAKE_BREAKOUT_RISK"
        elif current < prior_low: event = "BREAKDOWN" if volume_confirm else "LIQUIDITY_SWEEP_RISK"
        elif retest_high: event = "RETEST_OF_BREAKOUT"
        elif retest_low: event = "RETEST_OF_BREAKDOWN"
        elif range_width < .06 and obv_slope > 0 and price_slope <= 0: event = "ACCUMULATION"
        elif range_width < .06 and obv_slope < 0 and price_slope >= 0: event = "DISTRIBUTION"
        elif high_state == "HIGHER_HIGH" and low_state == "HIGHER_LOW": event = "UPTREND_STRUCTURE"
        elif high_state == "LOWER_HIGH" and low_state == "LOWER_LOW": event = "DOWNTREND_STRUCTURE"
        else: event = "RANGE_OR_TRANSITION"
        return {"status": "AVAILABLE", "structure": event, "high_pattern": high_state, "low_pattern": low_state,
                "prior_high": _number(prior_high), "prior_low": _number(prior_low), "volume_confirmed": bool(volume_confirm),
                "retest_detected": bool(retest_high or retest_low), "range_width_percent": _number(range_width, 4),
                "swing_highs": [_number(v) for v in highs.tail(5)], "swing_lows": [_number(v) for v in lows.tail(5)]}


class SupportResistanceEngine:
    def analyze(self, frame: pd.DataFrame) -> dict:
        data = frame.tail(min(500, len(frame))).copy(); current = float(data["close"].iloc[-1]); atr = float(data["atr"].iloc[-1])
        typical = (data["high"] + data["low"] + data["close"]) / 3
        turnover = data["amount"].where(data["amount"] > 0, typical * data["volume"])
        weights = turnover.clip(lower=0).to_numpy(); prices = typical.to_numpy()
        bins = min(30, max(10, len(data) // 20)); hist, edges = np.histogram(prices, bins=bins, weights=weights)
        profile = [(float((edges[i] + edges[i + 1]) / 2), float(hist[i])) for i in np.argsort(hist)[-6:]]
        swing_highs = data["high"][(data["high"] == data["high"].rolling(9, center=True).max())].dropna().tolist()
        swing_lows = data["low"][(data["low"] == data["low"].rolling(9, center=True).min())].dropna().tolist()
        vwap = float((typical * data["volume"]).sum() / max(data["volume"].sum(), 1e-12))
        low_anchor = int(data["low"].to_numpy().argmin()); high_anchor = int(data["high"].to_numpy().argmax())
        def anchored_vwap(begin: int) -> float:
            section=data.iloc[begin:]; section_typical=(section["high"]+section["low"]+section["close"])/3
            return float((section_typical*section["volume"]).sum()/max(section["volume"].sum(),1e-12))
        anchored_low,anchored_high=anchored_vwap(low_anchor),anchored_vwap(high_anchor)
        high, low = float(data["high"].max()), float(data["low"].min())
        fib = [low + (high - low) * ratio for ratio in (.236, .382, .5, .618, .786)]
        gaps=[]
        for index in range(1,len(data)):
            if data["low"].iloc[index] > data["high"].iloc[index-1]: gaps.append((float((data["low"].iloc[index]+data["high"].iloc[index-1])/2),"gap"))
            elif data["high"].iloc[index] < data["low"].iloc[index-1]: gaps.append((float((data["high"].iloc[index]+data["low"].iloc[index-1])/2),"gap"))
        indicators=[(float(data[column].iloc[-1]),column) for column in ("ma5","ma10","ma20","ma60","boll_lower","boll_upper") if pd.notna(data[column].iloc[-1])]
        candidates = ([(v, "swing") for v in swing_highs[-12:] + swing_lows[-12:]] +
                      [(v, "volume_profile_dense_node") for v, _ in profile] + [(vwap, "vwap"),
                      (anchored_low,"anchored_vwap_low"),(anchored_high,"anchored_vwap_high")] +
                      [(v, "fibonacci") for v in fib] + indicators + gaps[-8:] + [(high,"prior_high"),(low,"prior_low")])
        width = max(atr * .35, current * .001)
        def zones(side):
            values = [(p, source) for p, source in candidates if (p < current if side == "support" else p > current)]
            values.sort(key=lambda item: abs(item[0] - current)); output = []
            for center, source in values:
                if any(abs(center - item["center"]) <= width for item in output): continue
                touches = int(((data["low"] <= center + width) & (data["high"] >= center - width)).sum())
                confluence = sum(abs(center - other) <= width for other, _ in candidates)
                volume_score = next((volume / max(hist.max(), 1) for price, volume in profile if abs(price-center)<=width), 0)
                residence = int((data["close"].sub(center).abs() <= width).sum())
                strength = min(100, round(10 * min(touches, 5) + 8 * min(confluence, 4) + 8 * volume_score + 2*min(residence,5)))
                output.append({"lower": _number(center-width), "upper": _number(center+width), "center": _number(center),
                               "strength": strength, "touches": touches, "residence_bars":residence,
                               "confluence": confluence, "primary_source": source})
                if len(output) == 3: break
            return output
        supports, resistances = zones("support"), zones("resistance")
        return {"status": "AVAILABLE", "current_price": _number(current), "atr": _number(atr), "vwap": _number(vwap),
                "anchored_vwap":{"swing_low":_number(anchored_low),"swing_high":_number(anchored_high)},
                "supports": supports, "resistances": resistances, "volume_profile_source": "real candle volume distribution",
                "calculation": "real swing points + turnover-weighted volume profile + VWAP/anchored VWAP + MA/Bollinger + Fibonacci + gaps + prior high/low; zone width=0.35 ATR"}


class RiskEngine:
    def _optimized_multiplier(self, frame: pd.DataFrame, side: str, horizon_steps: int, regime: dict, asset_type: str) -> tuple[float, dict]:
        data = frame.dropna(subset=["atr"]).copy(); samples = []
        for index in range(20, len(data) - horizon_steps):
            entry = float(data["close"].iloc[index]); atr = float(data["atr"].iloc[index])
            if atr <= 0: continue
            future = data.iloc[index + 1:index + 1 + horizon_steps]
            adverse = entry - float(future["low"].min()) if side == "LONG" else float(future["high"].max()) - entry
            favorable = float(future["high"].max()) - entry if side == "LONG" else entry - float(future["low"].min())
            terminal = (float(future["close"].iloc[-1])-entry)*(1 if side=="LONG" else -1)
            samples.append((max(0,adverse/atr),max(0,favorable/atr),terminal/atr))
        if not samples:
            return 1.5,{"method":"historical grid search unavailable; safe fallback","samples":0,"tested":[]}
        observations=np.asarray(samples); split=max(30,int(len(observations)*.7)); train=observations[:split]
        volatility=float(regime["volatility_percentile"])
        lower=.9 if asset_type=="stock" else .8; upper=3.6 if volatility<.8 else 4.0
        tested=[]
        for multiplier in np.arange(lower,upper+.001,.1):
            reward_ratio=1.5
            outcomes=np.where(train[:,0]>=multiplier,-1.0,
                              np.where(train[:,1]>=multiplier*reward_ratio,reward_ratio,train[:,2]/multiplier))
            curve=np.cumsum(outcomes); peaks=np.maximum.accumulate(np.r_[0,curve])[1:]
            max_dd=float(np.max(peaks-curve)) if len(curve) else 0
            score=float(np.mean(outcomes)-.0025*max_dd)
            tested.append((float(multiplier),score,float(np.mean(train[:,0]>=multiplier)),float(np.mean(outcomes))))
        multiplier,score,hit_rate,mean_r=max(tested,key=lambda item:item[1])
        return multiplier,{"method":"chronological historical grid search maximizing mean R with drawdown penalty",
                           "samples":len(train),"holdout_samples":len(observations)-split,"selected_score":_number(score,4),"expected_r":_number(mean_r,4),
                           "estimated_stop_hit_rate":_number(hit_rate,4),"range":[lower,upper],"step":.1,
                           "regime":regime["primary"],"asset_type":asset_type}

    def analyze(self, frame: pd.DataFrame, levels: dict, regime: dict, side: str, horizon_steps: int, asset_type: str) -> dict:
        entry = float(frame["close"].iloc[-1]); atr = float(frame["atr"].iloc[-1]); k, optimization = self._optimized_multiplier(frame, side, horizon_steps, regime, asset_type)
        buffer = atr * (.12 + .18 * regime["volatility_percentile"])
        if side == "LONG":
            atr_stop = entry - atr * k
            swing = float(frame["low"].tail(40).min()) - buffer
            support = (levels["supports"][0]["lower"] - buffer) if levels["supports"] else atr_stop
            candidates = {"atr_stop": atr_stop, "swing_stop": swing, "support_stop": support}
            valid = [v for v in candidates.values() if v < entry]; stop = max(valid) if valid else atr_stop
        else:
            atr_stop = entry + atr * k
            swing = float(frame["high"].tail(40).max()) + buffer
            resistance = (levels["resistances"][0]["upper"] + buffer) if levels["resistances"] else atr_stop
            candidates = {"atr_stop": atr_stop, "swing_stop": swing, "resistance_stop": resistance}
            valid = [v for v in candidates.values() if v > entry]; stop = min(valid) if valid else atr_stop
        distance = abs(entry-stop); atr_distance = distance/max(atr, 1e-12)
        reason = "NORMAL" if .65 <= atr_distance <= 3.5 else "TOO_CLOSE_NOISE_RISK" if atr_distance < .65 else "TOO_FAR_RISK_REWARD_RISK"
        return {"entry": _number(entry), "stop_loss": _number(stop), "stop_distance": _number(distance),
                "stop_percent": _number(distance/entry, 4), "atr_distance": _number(atr_distance, 3),
                "atr_multiplier": _number(k, 3), "buffer": _number(buffer), "reasonableness": reason,
                "candidates": {key:_number(value) for key,value in candidates.items()}, "optimization": optimization,
                "trace": {"atr": _number(atr), "market_regime": regime["primary"], "volatility_percentile": regime["volatility_percentile"]}}


def _take_profits(entry: float, stop: float, side: str, levels: dict, frame: pd.DataFrame) -> list[dict]:
    risk = abs(entry-stop); atr = float(frame["atr"].iloc[-1]); historical_move = float(frame["return_1"].abs().rolling(20).sum().dropna().median() * entry)
    structural = levels["resistances"] if side == "LONG" else levels["supports"]
    prices = [item["center"] for item in structural]
    direction = 1 if side == "LONG" else -1
    prices += [entry + direction * max(risk * ratio, atr * ratio, historical_move * ratio / 3) for ratio in (1, 1.75, 2.5)]
    prices = sorted({float(p) for p in prices if (p > entry if side == "LONG" else p < entry)}, reverse=side == "SHORT")[:3]
    return [{"name": f"TP{i+1}", "price": _number(price), "reward": _number(abs(price-entry)),
             "risk_reward": _number(abs(price-entry)/max(risk,1e-12), 3)} for i,price in enumerate(prices)]


def _position_size(account: float, risk_percent: float, entry: float, stop: float, fee: float, slippage: float,
                   leverage: float, contract_multiplier: float, min_lot: float) -> dict:
    allowed = account * risk_percent; unit_risk = abs(entry-stop) + entry*(2*fee+2*slippage)
    raw = allowed / max(unit_risk*contract_multiplier, 1e-12)
    leverage_cap = account*leverage/max(entry*contract_multiplier,1e-12)
    quantity = min(raw, leverage_cap); quantity = floor(quantity/min_lot)*min_lot
    return {"account_equity": account, "max_risk_percent": risk_percent, "max_allowed_loss": _number(allowed,2),
            "per_unit_risk_with_costs": _number(unit_risk), "quantity": _number(max(0,quantity),8), "leverage": leverage,
            "contract_multiplier": contract_multiplier, "minimum_lot": min_lot, "notional": _number(max(0,quantity)*entry*contract_multiplier,2)}


def _validate_risk_plan(frame: pd.DataFrame, side: str, multiplier: float, reward_ratio: float, horizon_steps: int) -> dict:
    data=frame.dropna(subset=["atr"]); outcomes=[]; stop_hits=0;tp_hits=0
    start=max(30,int(len(data)*.7))
    for index in range(start,len(data)-horizon_steps):
        entry=float(data["close"].iloc[index]);risk=float(data["atr"].iloc[index])*multiplier
        if risk<=0: continue
        stop=entry-risk if side=="LONG" else entry+risk;tp=entry+risk*reward_ratio if side=="LONG" else entry-risk*reward_ratio
        path=data.iloc[index+1:index+1+horizon_steps]; stopped=bool(path["low"].min()<=stop) if side=="LONG" else bool(path["high"].max()>=stop)
        hit=bool(path["high"].max()>=tp) if side=="LONG" else bool(path["low"].min()<=tp)
        # Intrabar event order is unavailable in OHLC; use conservative stop-first accounting.
        if stopped: value=-1.0;stop_hits+=1
        elif hit: value=reward_ratio;tp_hits+=1
        else:
            value=(float(path["close"].iloc[-1])-entry)/risk*(1 if side=="LONG" else -1)
        outcomes.append(value)
    if not outcomes:return {"status":"INSUFFICIENT_DATA","samples":0}
    curve=np.cumsum(outcomes);peak=np.maximum.accumulate(np.r_[0,curve]);drawdown=peak[1:]-curve
    gains=sum(value for value in outcomes if value>0);losses=abs(sum(value for value in outcomes if value<0))
    return {"status":"AVAILABLE","samples":len(outcomes),"stop_hit_rate":_number(stop_hits/len(outcomes),4),
            "tp_hit_rate":_number(tp_hits/len(outcomes),4),"average_r":_number(np.mean(outcomes),4),
            "max_drawdown_r":_number(drawdown.max() if len(drawdown) else 0,4),"profit_factor":_number(gains/losses if losses else None,4),
            "expected_value_r":_number(np.mean(outcomes),4),"split":"last 30% chronological holdout",
            "intrabar_assumption":"conservative stop-first when both levels occur in one candle"}


def _multi_timeframe(frame: pd.DataFrame, source_interval: str, prediction: dict) -> dict:
    minutes = INTERVAL_MINUTES[source_interval]; targets = {"15m":15,"1H":60,"4H":240,"1D":1440}; output = {}
    raw = frame.set_index(pd.DatetimeIndex(frame["timestamp_utc"]))
    for label,target in targets.items():
        if target < minutes or target % minutes: output[label] = {"status":"NO_DATA", "reason":"source bars are coarser"}; continue
        if target == minutes: data = raw
        else:
            data = raw.resample(f"{target}min").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
        if len(data)<20: output[label] = {"status":"INSUFFICIENT_DATA"}; continue
        returns=data["close"].pct_change(); trend=float(data["close"].iloc[-1]/data["close"].rolling(20).mean().iloc[-1]-1)
        signed=np.sign(returns).fillna(0)*data["volume"]; flow=float(signed.tail(10).sum()/max(data["volume"].tail(10).sum(),1e-12)); vol=float(returns.tail(20).std())
        local_atr=float(pd.concat([(data["high"]-data["low"]),(data["high"]-data["close"].shift()).abs(),(data["low"]-data["close"].shift()).abs()],axis=1).max(axis=1).rolling(14).mean().iloc[-1])
        support=float(data["low"].tail(min(40,len(data))).min()); resistance=float(data["high"].tail(min(40,len(data))).max())
        horizon=label if label in prediction.get("predictions",{}) else None; model=prediction["predictions"].get(horizon,{}) if horizon else {}
        output[label]={"status":"AVAILABLE","trend":"UP" if trend>.002 else "DOWN" if trend<-.002 else "FLAT",
                       "flow":"UP" if flow>.03 else "DOWN" if flow<-.03 else "FLAT", "sentiment":"POSITIVE" if trend+flow>0 else "NEGATIVE",
                       "momentum":_number(data["close"].pct_change(5).iloc[-1],5),"volatility":_number(vol,5),
                       "support":_number(support),"resistance":_number(resistance),"atr_risk_percent":_number(local_atr/data["close"].iloc[-1],5),
                       "prediction":model.get("prediction"),"prediction_confidence":model.get("confidence_score"),"bars":len(data)}
    available=[v for v in output.values() if v.get("status")=="AVAILABLE"]
    score=sum({"UP":1,"FLAT":0,"DOWN":-1}[v["trend"]] for v in available)
    return {"matrix":output,"consensus":"BULLISH" if score>1 else "BEARISH" if score<-1 else "MIXED","available_timeframes":len(available)}


def analyze_v3(candles: list[dict], prediction: dict, interval: str, asset_type: str, symbol: str,
               account_equity: float = 100000, max_risk_percent: float = .01, leverage: float = 1,
               contract_multiplier: float = 1, minimum_lot: float | None = None,
               derivatives: dict | None = None, rotation: list[dict] | None = None,
               external_context: dict | None = None) -> dict:
    frame=feature_frame(candles)
    external_context=external_context or {}
    primary=prediction["predictions"].get("1H")
    if not primary or not primary.get("prediction"):
        primary=next(v for v in prediction["predictions"].values() if v.get("prediction"))
    flow=CapitalFlowEngine().analyze(frame,derivatives); regime=MarketRegimeEngine().analyze(frame,flow,prediction["feature_availability"]["feature_coverage"],external_context)
    structure=MarketStructureEngine().analyze(frame); levels=SupportResistanceEngine().analyze(frame)
    side="LONG" if primary["prediction"]=="UP" else "SHORT" if primary["prediction"]=="DOWN" else "LONG"
    steps=max(1,int(primary["nominal_bar_count"])); risk=RiskEngine().analyze(frame,levels,regime,side,steps,asset_type)
    tps=_take_profits(risk["entry"],risk["stop_loss"],side,levels,frame)
    if len(tps)<3:
        direction=1 if side=="LONG" else -1
        while len(tps)<3:
            ratio=len(tps)+1; price=risk["entry"]+direction*risk["stop_distance"]*ratio
            tps.append({"name":f"TP{ratio}","price":_number(price),"reward":_number(abs(price-risk["entry"])),"risk_reward":float(ratio)})
    probs=primary["probabilities"]; pwin=probs["up"] if side=="LONG" else probs["down"]; ploss=probs["down"] if side=="LONG" else probs["up"]
    profile=prediction["model"].get("asset_profile",{"confidence_factor":1.0,"slippage_factor":1.0})
    slippage=(.001 if asset_type=="crypto" else .0005)*profile["slippage_factor"]
    target=tps[1]; costs=risk["entry"]*(.001 if asset_type=="crypto" else .0003)*2+risk["entry"]*slippage*2
    expected_value=pwin*target["reward"]-ploss*risk["stop_distance"]-costs
    ev_percent=expected_value/risk["entry"]
    min_lot=minimum_lot or (.000001 if asset_type=="crypto" else 100)
    event=external_context.get("event",{"status":"NO_DATA","risk":"UNKNOWN","detail":"No verified event calendar configured."})
    event_factor=.5 if event.get("risk")=="HIGH" else .75 if event.get("risk")=="MEDIUM" else 1.0
    effective_risk=max_risk_percent*profile["confidence_factor"]*event_factor
    position=_position_size(account_equity,effective_risk,risk["entry"],risk["stop_loss"],.001 if asset_type=="crypto" else .0003,
                            slippage,leverage,contract_multiplier,min_lot)
    position["requested_risk_percent"]=max_risk_percent;position["liquidity_adjustment"]=profile["confidence_factor"]
    consensus=float(primary["model_consensus"]); model_coverage=float(primary["feature_coverage"]); rr=float(target["risk_reward"])
    applicable=[value for value in external_context.values() if value.get("status")!="NOT_APPLICABLE"]
    external_coverage=sum(value.get("status") in {"AVAILABLE","PARTIAL_DATA"} for value in applicable)/max(1,len(applicable))
    coverage=.7*model_coverage+.3*external_coverage
    raw_confidence=float(primary.get("confidence_score",max(probs.values())*100))/100
    adjusted_confidence=raw_confidence*event_factor*(.85+.15*external_coverage)
    direction_strength=max(probs.values()); flow_strength=min(1,abs(flow["net_flow_ratio"])*8); trend_strength=min(1,abs(regime["trend_score"]));
    ev_score=float(np.clip(.5+ev_percent/max(risk["stop_percent"],1e-6)/4,0,1)); rr_score=float(np.clip(rr/3,0,1))
    components={"model_probability":direction_strength,"model_consensus":consensus,"flow":flow_strength,"trend":trend_strength,
                "risk_reward":rr_score,"expected_value":ev_score,"data_completeness":coverage,"volatility_suitability":1-abs(regime["volatility_percentile"]-.55)}
    weights={"model_probability":.18,"model_consensus":.12,"flow":.12,"trend":.12,"risk_reward":.16,"expected_value":.16,"data_completeness":.09,"volatility_suitability":.05}
    opportunity=round(100*sum(components[k]*weights[k] for k in weights))
    if coverage<.4: decision="NO_TRADE"; reason="DATA_QUALITY_TOO_LOW"
    elif expected_value<=0: decision="NO_TRADE"; reason="NEGATIVE_EXPECTED_VALUE"
    elif event.get("risk")=="HIGH": decision="WAIT"; reason="HIGH_IMPACT_EVENT_RISK"
    elif primary["prediction"]=="FLAT": decision="HOLD"; reason="BASE_CASE_IS_RANGE"
    elif direction_strength<.45 or consensus<.55: decision="WAIT"; reason="MODEL_UNCERTAINTY"
    elif risk["reasonableness"]!="NORMAL": decision="WAIT"; reason=risk["reasonableness"]
    else: decision="BUY" if side=="LONG" else "SELL"; reason="POSITIVE_EXPECTED_VALUE_AND_ACCEPTABLE_RISK"
    if decision=="WAIT" and levels["supports"] and side=="LONG": guidance=f"WAIT_FOR_SUPPORT_RETEST_{levels['supports'][0]['lower']}_{levels['supports'][0]['upper']}"
    elif decision=="WAIT" and levels["resistances"] and side=="SHORT": guidance=f"WAIT_FOR_RESISTANCE_RETEST_{levels['resistances'][0]['lower']}_{levels['resistances'][0]['upper']}"
    elif decision=="NO_TRADE": guidance="NO_POSITION_UNTIL_EXPECTED_VALUE_OR_DATA_QUALITY_IMPROVES"
    else: guidance="EXECUTE_ONLY_AFTER_PRICE_AND_VOLUME_CONFIRMATION"
    regime_change=[]
    if abs(flow["flow_acceleration"])>.08: regime_change.append("FLOW_REVERSAL_OR_ACCELERATION")
    if regime["volatility_percentile"]>.9: regime_change.append("VOLATILITY_SPIKE")
    if event.get("risk")=="HIGH": regime_change.append("HIGH_IMPACT_EVENT_WITHIN_36H")
    if structure["structure"] in {"BREAKDOWN","FAKE_BREAKOUT_RISK","LIQUIDITY_SWEEP_RISK"}: regime_change.append(structure["structure"])
    scenarios=[{"name":"BULL_CASE","probability":probs["up"],"trigger":levels["resistances"][0] if levels["resistances"] else None,"target":tps[-1]["price"]},
               {"name":"BASE_CASE","probability":probs["flat"],"range":{"lower":levels["supports"][0]["upper"] if levels["supports"] else None,"upper":levels["resistances"][0]["lower"] if levels["resistances"] else None}},
               {"name":"BEAR_CASE","probability":probs["down"],"trigger":levels["supports"][0] if levels["supports"] else None,"target":risk["stop_loss"]}]
    volume_confirmation=1.0 if structure["volume_confirmed"] else 0.0
    breakout_probability=float(np.clip(.45*probs["up"]+.2*max(0,flow["net_flow_ratio"]*4)+.2*max(0,regime["trend_score"])+.15*volume_confirmation,0,1))
    fake_breakout=float(np.clip((1-breakout_probability)*(.65 if not structure["volume_confirmed"] else .35),0,1))
    continuation=float(np.clip(breakout_probability*(.55+.45*flow["flow_persistence"]),0,1))
    risk_validation=_validate_risk_plan(frame,side,risk["atr_multiplier"],tps[0]["risk_reward"],steps)
    uncertainty=1-direction_strength;risk_points=.3*regime["volatility_percentile"]+.22*uncertainty+.18*(1-coverage)+.18*min(1,abs(flow["flow_acceleration"])*5)+(.12 if event.get("risk")=="HIGH" else .06 if event.get("risk")=="MEDIUM" else 0)
    risk_level="EXTREME" if risk_points>=.8 else "HIGH" if risk_points>=.6 else "MEDIUM" if risk_points>=.35 else "LOW"
    return {"engine_version":"3.0","symbol":symbol,"asset_type":asset_type,"interval":interval,
            "prediction_timestamp":datetime.now(timezone.utc).isoformat(),"data_timestamp":frame["timestamp_utc"].iloc[-1].isoformat(),
            "model_version":prediction["engine_version"],"feature_version":"3.0","market_regime":regime,"capital_flow":flow,
            "capital_rotation":{"status":"AVAILABLE" if rotation else "NO_DATA","assets":rotation or [],"source":"real OHLCV relative flow/return ranking" if rotation else None},
            "market_structure":structure,"support_resistance":levels,"risk_plan":risk,"take_profits":tps,
            "breakout_analysis":{"breakout_probability":_number(breakout_probability,4),"fake_breakout_risk":_number(fake_breakout,4),
                                   "continuation_probability":_number(continuation,4),"inputs":{"model_up":probs["up"],"flow_ratio":flow["net_flow_ratio"],"trend_score":regime["trend_score"],"volume_confirmed":structure["volume_confirmed"]}},
            "position_sizing":position,"risk_reward":{"tp1":tps[0]["risk_reward"],"tp2":tps[1]["risk_reward"],"tp3":tps[2]["risk_reward"],"breakeven_rr":_number(ploss/max(pwin,1e-12),3)},
            "expected_value":{"value_per_unit":_number(expected_value),"percent":_number(ev_percent,4),"p_win":pwin,"p_loss":ploss,"costs":_number(costs),"positive":bool(expected_value>0)},
            "scenarios":scenarios,"multi_timeframe":_multi_timeframe(frame,interval,prediction),
            "regime_change_risk":{"active":bool(regime_change),"signals":regime_change},
            "external_context":external_context,"event_risk":event,
            "confidence_adjustment":{"raw":_number(raw_confidence,4),"adjusted":_number(adjusted_confidence,4),
                                     "event_factor":event_factor,"external_context_coverage":_number(external_coverage,4)},
            "event_volatility_forecast":{"status":"NO_DATA","detail":"Requires verified historical event timestamps."},
            "risk_level":{"level":risk_level,"score":_number(risk_points,4),"event_component":event.get("risk","UNKNOWN")},"risk_validation":risk_validation,
            "trade_opportunity":{"score":opportunity,"components":{k:_number(v,4) for k,v in components.items()},"weights":weights},
            "decision":{"action":decision,"direction":side,"reason":reason,"guidance":guidance,
                        "entry_zone":{"lower":_number(risk["entry"]-frame["atr"].iloc[-1]*.2),"upper":_number(risk["entry"]+frame["atr"].iloc[-1]*.2)}},
            "evidence_chain":{"prediction":primary,"flow_source":flow["source"],"level_calculation":levels["calculation"],"stop_calculation":risk,
                              "external_feature_status":prediction["feature_availability"]["feature_status"],"current_external_context":external_context},
            "notice":"Mathematical scenarios and calibrated model outputs are research estimates, not guaranteed outcomes or investment advice."}
