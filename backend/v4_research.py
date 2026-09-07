from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .ai_engine import FEATURES, _aligned_dataset, _metrics, _purged_train_end, feature_frame
from .horizons import target_indices


def _number(value, digits=5):
    try:
        value=float(value)
        return round(value,digits) if np.isfinite(value) else None
    except (TypeError,ValueError): return None


def _timestamps(rows: list[dict]) -> pd.DataFrame:
    if not rows:return pd.DataFrame()
    frame=pd.DataFrame(rows)
    frame["timestamp"]=pd.to_datetime(frame["timestamp"],utc=True)
    return frame.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")


class DataQualityEngine:
    def analyze(self, frame: pd.DataFrame, source: str, external: dict, conflicts: list[dict] | None=None) -> dict:
        required=["open","high","low","close","volume"]
        completeness=float(frame[required].notna().mean().mean())
        aligned=float(frame[FEATURES].notna().mean().mean())
        sources={source}
        available=0; applicable=0
        for value in external.values():
            if not isinstance(value,dict) or value.get("status") in {"NOT_APPLICABLE","NOT_APPLICABLE_OR_NO_DATA"}:continue
            applicable+=1
            if value.get("status") in {"AVAILABLE","PARTIAL_DATA"}:available+=1
            if value.get("source"):sources.add(str(value["source"]))
        external_coverage=available/max(1,applicable)
        latest=pd.Timestamp(frame["timestamp_utc"].iloc[-1]);now=pd.Timestamp.now(tz="UTC")
        age_hours=max(0,(now-latest).total_seconds()/3600)
        # Market closures can legitimately make daily/equity bars older. This is
        # exposed separately rather than silently labelling them live.
        freshness=max(0,1-age_hours/72)
        conflict_count=len(conflicts or [])
        conflict_score=max(0,1-conflict_count*.2)
        score=100*(.28*completeness+.22*aligned+.18*external_coverage+.12*min(1,len(sources)/4)+.12*freshness+.08*conflict_score)
        return {"score":round(score,1),"grade":"HIGH" if score>=85 else "MEDIUM" if score>=65 else "LOW",
                "components":{"freshness":_number(freshness,4),"completeness":_number(completeness,4),
                              "feature_alignment":_number(aligned,4),"external_coverage":_number(external_coverage,4),
                              "source_count":len(sources),"conflict_count":conflict_count},
                "data_age_hours":_number(age_hours,2),"sources":sorted(sources),"conflicts":conflicts or [],
                "method":"weighted observed-data quality; no imputed provider availability"}


class CrossAssetEngine:
    def analyze(self, target: str, target_rows: list[dict], peers: dict[str,list[dict]]) -> dict:
        frames={target:_timestamps(target_rows)}
        frames.update({name:_timestamps(rows) for name,rows in peers.items() if rows})
        returns=[]
        for name,frame in frames.items():
            if not frame.empty:returns.append(frame["close"].rename(name).pct_change())
        if len(returns)<2:return {"status":"DATA_INSUFFICIENT","reason":"至少需要两个资产的历史重叠K线","correlations":[]}
        aligned=pd.concat(returns,axis=1).sort_index().dropna(how="all")
        if target not in aligned or aligned[target].notna().sum()<30:return {"status":"DATA_INSUFFICIENT","reason":"历史重叠样本不足","samples":int(aligned[target].notna().sum()),"correlations":[]}
        window=min(120,int(aligned[target].notna().sum())); output=[]
        for name in aligned.columns:
            if name==target:continue
            pair=aligned[[target,name]].dropna().tail(window)
            if len(pair)<30:continue
            corr=pair[target].corr(pair[name])
            output.append({"pair":f"{target} ↔ {name}","correlation":_number(corr,4),"samples":len(pair),"window":"rolling latest observations"})
        target_momentum=float(aligned[target].dropna().tail(24).sum())
        usable_peers=[name for name in aligned.columns if name!=target and len(aligned[[target,name]].dropna())>=30]
        peer_momentum=float(aligned[usable_peers].tail(24).mean(axis=1).sum()) if usable_peers else 0
        environment="FAVORABLE" if target_momentum>0 and peer_momentum>0 else "UNFAVORABLE" if target_momentum<0 and peer_momentum<0 else "NEUTRAL"
        return {"status":"AVAILABLE" if output else "DATA_INSUFFICIENT","environment":environment,
                "correlations":output,"aligned_samples":max([item["samples"] for item in output],default=0),"source":"pairwise timestamp-aligned real historical closes"}


class NewsEventEngine:
    TYPES={"财报":("财报","业绩","earnings"),"政策监管":("政策","监管","处罚","批准","approval","regulation"),
           "利率通胀就业":("利率","通胀","cpi","就业","非农","fomc"),"并购合作产品":("并购","收购","合作","产品","merger"),
           "诉讼地缘":("诉讼","战争","地缘","冲突","lawsuit","war"),"ETF融资评级":("etf","融资","评级","增持","减持")}
    def analyze(self, news: dict, symbol: str, candles: list[dict], collected_at: str) -> dict:
        seen={};clusters=[];events=[]
        prices=_timestamps(candles)
        for item in news.get("headlines",[]):
            title=item.get("title","").strip();norm=re.sub(r"[^a-z0-9\u4e00-\u9fff]","",title.lower())
            # Publisher suffixes differ while the substantive title is often identical.
            shingles={norm[i:i+3] for i in range(max(1,len(norm)-2))}
            match=None
            for prior_key,prior in clusters:
                similarity=len(shingles&prior)/max(1,len(shingles|prior))
                if similarity>=.72:match=prior_key;break
            raw_key=hashlib.sha1(norm[:80].encode("utf-8")).hexdigest()[:12]
            key=match or raw_key
            relation="DUPLICATE" if raw_key in seen else "FOLLOW_UP" if match else "ORIGINAL"
            seen.setdefault(raw_key,title)
            if not match:clusters.append((key,shingles))
            published=pd.to_datetime(item.get("published"),utc=True,errors="coerce")
            event_type=next((name for name,words in self.TYPES.items() if any(word in title.lower() for word in words)),"市场动态")
            signal=int(item.get("keyword_signal") or 0)
            priced={"status":"DATA_INSUFFICIENT","reason":"发布时间与本地K线没有足够的前后窗口"}
            if pd.notna(published) and not prices.empty:
                before=prices.loc[prices.index<published,"close"].tail(8);after=prices.loc[prices.index>=published,"close"].head(4)
                if len(before)>=2 and len(after)>=2:
                    pre=float(before.iloc[-1]/before.iloc[0]-1);post=float(after.iloc[-1]/after.iloc[0]-1)
                    priced_score=float(np.clip(abs(pre)/(abs(pre)+abs(post)+1e-9),0,1))
                    priced={"status":"AVAILABLE","score":_number(priced_score,4),"pre_return":_number(pre,5),"post_return":_number(post,5),
                            "assessment":"MOSTLY_PRICED" if priced_score>.67 else "PARTLY_PRICED" if priced_score>.34 else "NOT_YET_PRICED"}
            events.append({"event_id":key,"event_type":event_type,"affected_asset":symbol,"affected_sector":None,
                           "direction":"POSITIVE" if signal>0 else "NEGATIVE" if signal<0 else "NEUTRAL",
                           "impact_strength":abs(signal),"time_horizon":"UNKNOWN","confidence":.45 if signal else .25,
                           "source":news.get("source"),"title":title,"publication_time":None if pd.isna(published) else published.isoformat(),
                           "first_report_time":None if pd.isna(published) else published.isoformat(),"collected_at":collected_at,
                           "event_time":None,"cluster_relation":relation,"priced_in":priced})
        unique=[event for event in events if event["cluster_relation"]=="ORIGINAL"]
        return {"status":"AVAILABLE" if unique else "NO_DATA","events":unique,"duplicate_count":len(events)-len(unique),
                "method":"deterministic headline classification and exact-normalized clustering; no LLM facts",
                "historical_training_status":"DATA_INSUFFICIENT"}


class PathRiskEngine:
    def analyze(self, frame: pd.DataFrame, interval: str, asset_type: str, horizon: str, side: str,
                stop_distance: float, targets: list[dict]) -> dict:
        indices=target_indices(pd.DatetimeIndex(frame["timestamp_utc"]),asset_type,interval,horizon)
        direction=1 if side=="LONG" else -1;mae=[];mfe=[];returns=[]
        for start,end in enumerate(indices):
            if end<=start:continue
            entry=float(frame["close"].iloc[start]);path=frame.iloc[start+1:end+1]
            if side=="LONG": adverse=(path["low"].min()/entry-1);favorable=(path["high"].max()/entry-1)
            else: adverse=(entry/path["high"].max()-1);favorable=(entry/path["low"].min()-1)
            mae.append(float(adverse));mfe.append(float(favorable));returns.append(float((frame["close"].iloc[end]/entry-1)*direction))
        if len(returns)<60:return {"status":"DATA_INSUFFICIENT","samples":len(returns)}
        entry=float(frame["close"].iloc[-1]);stop_pct=stop_distance/max(entry,1e-12)
        tp=[]
        for item in targets:
            pct=abs(float(item["price"])-entry)/max(entry,1e-12)
            tp.append({"name":item["name"],"historical_hit_probability":_number(np.mean(np.asarray(mfe)>=pct),4),"distance_percent":_number(pct,5)})
        return {"status":"AVAILABLE","samples":len(returns),"mae":{"median":_number(np.median(mae),5),"p10":_number(np.quantile(mae,.1),5),
                 "winning_trade_median":_number(np.median([v for v,r in zip(mae,returns) if r>0]),5) if any(r>0 for r in returns) else None},
                "mfe":{"median":_number(np.median(mfe),5),"p75":_number(np.quantile(mfe,.75),5)},
                "stop_hit_probability":_number(np.mean(np.asarray(mae)<=-stop_pct),4),"take_profit_probabilities":tp,
                "expected_directional_return":_number(np.mean(returns),5),"method":"full future OHLC path; conservative barrier statistics"}


class ReturnDistributionEngine:
    def analyze(self, frame: pd.DataFrame, interval: str, asset_type: str, horizon: str) -> dict:
        indices=target_indices(pd.DatetimeIndex(frame["timestamp_utc"]),asset_type,interval,horizon)
        future=np.full(len(frame),np.nan);vol=np.full(len(frame),np.nan);close=frame["close"].to_numpy(float)
        for i,end in enumerate(indices):
            if end>i:
                future[i]=close[end]/close[i]-1
                vol[i]=float(frame["return_1"].iloc[i+1:end+1].std(ddof=0))
        valid=frame[FEATURES].notna().all(axis=1)&np.isfinite(future)&np.isfinite(vol)
        x=frame.loc[valid,FEATURES];yr=future[valid];yv=vol[valid]
        if len(x)<140:return {"status":"DATA_INSUFFICIENT","samples":len(x)}
        split=int(len(x)*.82);train_end=max(1,split-max(1,int(np.median(indices[indices>=0]-np.arange(len(indices))[indices>=0]))))
        model=RandomForestRegressor(n_estimators=160,max_depth=7,min_samples_leaf=5,random_state=42,n_jobs=1)
        model.fit(x.iloc[:train_end],yr[:train_end]);pred=model.predict(x.iloc[split:]);current=float(model.predict(frame[FEATURES].dropna().iloc[[-1]])[0])
        vol_model=RandomForestRegressor(n_estimators=120,max_depth=6,min_samples_leaf=5,random_state=43,n_jobs=1)
        vol_model.fit(x.iloc[:train_end],yv[:train_end]);current_vol=float(vol_model.predict(frame[FEATURES].dropna().iloc[[-1]])[0])
        return {"status":"AVAILABLE","samples":len(x),"expected_return":_number(current,5),"expected_volatility":_number(max(0,current_vol),5),
                "holdout_mae":_number(mean_absolute_error(yr[split:],pred),5),"holdout_samples":len(pred),
                "method":"purged chronological RandomForest regressions; final holdout excluded from fitting"}


class AnomalyEngine:
    def analyze(self, frame: pd.DataFrame, derivatives: dict|None, news_events: dict) -> dict:
        def z(series):
            sample=series.dropna().tail(120);return 0 if len(sample)<20 or sample.std()==0 else float((sample.iloc[-1]-sample.mean())/sample.std())
        checks={"volume_spike":z(frame["volume"]),"price_spike":z(frame["return_1"].abs()),"volatility_spike":z(frame["volatility"])}
        if derivatives and derivatives.get("funding_rate_percentile") is not None:
            checks["funding_spike"]=(float(derivatives["funding_rate_percentile"])-.5)*4
        checks["news_spike"]=max(0,(len(news_events.get("events",[]))-5)/5)
        active=[{"type":name,"z_score":_number(value,3)} for name,value in checks.items() if abs(value)>=2]
        return {"status":"ANOMALY" if active else "NORMAL","signals":active,"all_checks":{k:_number(v,3) for k,v in checks.items()},
                "confidence_multiplier":.8 if active else 1.0}


class PortfolioRiskEngine:
    def analyze(self, returns: pd.DataFrame, weights: dict[str,float]) -> dict:
        columns=[name for name in weights if name in returns]
        aligned=returns[columns].dropna() if columns else pd.DataFrame()
        if len(columns)<2 or len(aligned)<60:return {"status":"DATA_INSUFFICIENT","reason":"组合至少需要两个持仓及60个重叠收益样本"}
        w=np.asarray([weights[name] for name in columns],float);w=w/w.sum();series=aligned.to_numpy()@w
        var=-float(np.quantile(series,.05));tail=series[series<=np.quantile(series,.05)];cvar=-float(tail.mean())
        vol=float(series.std(ddof=1));curve=np.cumprod(1+series);dd=float(np.max(1-curve/np.maximum.accumulate(curve)))
        return {"status":"AVAILABLE","assets":columns,"samples":len(series),"volatility_per_bar":_number(vol,5),
                "var_95_per_bar":_number(var,5),"cvar_95_per_bar":_number(cvar,5),"max_drawdown":_number(dd,5),
                "correlation":aligned.corr().round(4).to_dict(),"concentration":_number(float(np.sum(w*w)),4)}


def factor_ablation(frame: pd.DataFrame, interval: str, asset_type: str, horizon: str) -> dict:
    x,y,meta=_aligned_dataset(frame,asset_type,interval,horizon)
    target_gap=(pd.to_datetime(meta["target_time"]).to_numpy()-pd.to_datetime(meta["feature_time"]).to_numpy())
    typical_gap=pd.to_timedelta(pd.Series(target_gap).median())
    bar_gap=pd.to_datetime(meta["feature_time"]).diff().median()
    embargo=max(1,int(round(typical_gap/bar_gap))) if pd.notna(bar_gap) and bar_gap>pd.Timedelta(0) else 1
    test_start=int(len(x)*.82);train_end=_purged_train_end(meta,test_start,embargo)
    if train_end<100 or len(x)-test_start<25:return {"status":"DATA_INSUFFICIENT","samples":len(x)}
    groups={"Technical Only":[name for name in FEATURES if name not in {"flow_pressure","sentiment_score"}],
            "Technical + Flow":[name for name in FEATURES if name!="sentiment_score"],
            "Technical + Flow + Sentiment":FEATURES}
    experiments={}
    future=meta["future_return"].iloc[test_start:].to_numpy(float)
    for name,columns in groups.items():
        model=make_pipeline(StandardScaler(),LogisticRegression(C=.75,class_weight="balanced",max_iter=1000,random_state=42))
        model.fit(x[columns].iloc[:train_end],y.iloc[:train_end]);raw=model.predict_proba(x[columns].iloc[test_start:])
        probabilities=np.zeros((len(raw),3))
        for idx,cls in enumerate(model.classes_):probabilities[:,int(cls)+1]=raw[:,idx]
        metrics=_metrics(y.iloc[test_start:],probabilities);signal=np.array([-1,0,1])[np.argmax(probabilities,axis=1)]
        returns=signal*future;curve=np.cumprod(1+returns);peak=np.maximum.accumulate(curve);drawdown=float(np.max(1-curve/peak))
        std=float(np.std(returns,ddof=1));sharpe=float(np.mean(returns)/std*np.sqrt(252)) if std>0 else 0
        wins=returns[returns>0].sum();losses=abs(returns[returns<0].sum());score=probabilities[:,2]-probabilities[:,0]
        ic=float(pd.Series(score).corr(pd.Series(future))) if np.std(score)>0 and np.std(future)>0 else 0
        experiments[name]={"status":"AVAILABLE","features":columns,"samples":len(returns),**metrics,
                           "ic":_number(ic,4),"icir":"DATA_INSUFFICIENT_SINGLE_WINDOW","return":_number(curve[-1]-1,4),
                           "sharpe":_number(sharpe,4),"max_drawdown":_number(drawdown,4),
                           "profit_factor":_number(wins/losses,4) if losses else None}
    ordered=list(groups);increments={}
    for previous,current in zip(ordered,ordered[1:]):
        increments[current]={"accuracy_delta":_number(experiments[current]["accuracy"]-experiments[previous]["accuracy"],4),
                             "sharpe_delta":_number(experiments[current]["sharpe"]-experiments[previous]["sharpe"],4),
                             "ic_delta":_number(experiments[current]["ic"]-experiments[previous]["ic"],4)}
    return {"status":"AVAILABLE","validation":"purged chronological holdout","experiments":experiments,"incremental_value":increments,
            "not_testable":{"+ News":"DATA_INSUFFICIENT: no historical news archive","+ Macro":"DATA_INSUFFICIENT: not in aligned feature rows",
                            "+ Fundamental":"DATA_INSUFFICIENT: no point-in-time statements","+ OnChain":"DATA_INSUFFICIENT: no historical aligned series"}}


def build_research_layer(candles: list[dict], interval: str, asset_type: str, symbol: str, prediction: dict,
                         decision: dict, source: str, external: dict, peers: dict[str,list[dict]],
                         derivatives: dict|None=None, conflicts: list[dict]|None=None) -> dict:
    frame=feature_frame(candles);now=datetime.now(timezone.utc).isoformat()
    primary=prediction["predictions"].get("1H") or next(v for v in prediction["predictions"].values() if v.get("prediction"))
    horizon=primary["horizon"];side=decision["decision"]["direction"]
    news=NewsEventEngine().analyze(external.get("news",{}),symbol,candles,now)
    quality=DataQualityEngine().analyze(frame,source,external,conflicts)
    cross=CrossAssetEngine().analyze(symbol,candles,peers)
    path=PathRiskEngine().analyze(frame,interval,asset_type,horizon,side,decision["risk_plan"]["stop_distance"],decision["take_profits"])
    distribution=ReturnDistributionEngine().analyze(frame,interval,asset_type,horizon)
    anomaly=AnomalyEngine().analyze(frame,derivatives,news)
    event_mode=external.get("event",{}).get("risk")=="HIGH"
    invalidation=[]
    levels=decision["support_resistance"]
    if side=="LONG":invalidation.append({"condition":"PRICE_BELOW_SUPPORT","level":levels["supports"][0]["lower"] if levels["supports"] else decision["risk_plan"]["stop_loss"]})
    else:invalidation.append({"condition":"PRICE_ABOVE_RESISTANCE","level":levels["resistances"][0]["upper"] if levels["resistances"] else decision["risk_plan"]["stop_loss"]})
    invalidation += [{"condition":"FLOW_DIRECTION_REVERSES","current":decision["capital_flow"]["direction"]},
                     {"condition":"MARKET_SWITCHES_RISK_MODE","current":decision["market_regime"]["risk_mode"]},
                     {"condition":"HIGH_IMPACT_NEGATIVE_EVENT"}]
    ablation=factor_ablation(frame,interval,asset_type,horizon)
    ablation["core_model"]={"status":"PASS" if primary.get("validation_scheme",{}).get("leakage_check") else "FAIL",
                            "factors":["technical","price-volume flow","price-volume sentiment"],"metrics":primary.get("model_metrics")}
    return {"engine_version":"4.0","generated_at":now,"historical_data_boundary":frame["timestamp_utc"].iloc[-1].isoformat(),
            "live_data_collected_at":now,"operating_mode":"EVENT_MODE" if event_mode else "NORMAL_MODE",
            "event_mode_policy":{"active":event_mode,"position_multiplier":.5 if event_mode else 1.0,
                                 "note":"V3 risk engine reduces position and confidence; no unvalidated prediction-weight override"},
            "data_quality":quality,"cross_asset":cross,"news_events":news,
            "path_risk":path,"return_distribution":distribution,"anomaly_detection":anomaly,
            "sentiment_composite":{"status":"PARTIAL_DATA","score":_number((frame["sentiment_score"].iloc[-1]+float(external.get("news",{}).get("sentiment_score") or 0))/2,4),
                                   "available_components":["price_volume","news_headline_keywords"],
                                   "missing_components":["social","put_call","options_skew","historical_breadth"]},
            "feature_ablation":ablation,"financial_history":{"status":external.get("financial_history",{}).get("status","NOT_APPLICABLE"),
                "records":len(external.get("financial_history",{}).get("history",[])),"point_in_time_enforced":True,
                "model_training_status":"DATA_INSUFFICIENT","surprise_status":external.get("financial_history",{}).get("surprise_status","DATA_INSUFFICIENT")},
            "onchain_regime":{"status":"DATA_INSUFFICIENT","current_snapshot":external.get("onchain"),"historical_alignment":False},
            "economic_surprise":{"status":"DATA_INSUFFICIENT","reason":"calendar has forecast/previous but no verified released actual history"},
            "portfolio_risk":{"status":"DATA_INSUFFICIENT","reason":"single-asset request does not contain a complete portfolio return matrix"},
            "scenario_sensitivity":[{"shock":"support_or_resistance_break","effect":"INVALIDATE"},
                                    {"shock":"flow_reversal","effect":"confidence_down_and_recalculate"},
                                    {"shock":"risk_mode_flip","effect":"position_down_and_recalculate"}],
            "invalidation_conditions":invalidation,"prediction_lifecycle":{"status":"ACTIVE","expires_at":primary["future_timestamp"],
               "refresh_triggers":["new_bar","price_level_break","flow_reversal","major_event","volatility_spike"]},
            "model_governance":{"online_update":"VALIDATE_BEFORE_REPLACE","retirement":"INSUFFICIENT_RESOLVED_PREDICTIONS",
                                "extended_model_validation":"DATA_INSUFFICIENT"}}
