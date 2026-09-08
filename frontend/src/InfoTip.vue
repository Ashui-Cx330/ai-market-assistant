<script setup lang="ts">
defineProps<{term:string}>()
const definitions:Record<string,string>={
  'AI Score':'当前真实量价、技术指标与已采集新闻的综合信号评分，不是上涨概率、准确率或收益保证。',
  'Prediction':'模型对指定未来周期方向的经校准概率估计；概率会随数据变化，不构成承诺。',
  'Confidence':'模型在当前输入与样本条件下的一致性/稳定性估计，不等于现实成功率。',
  'RSI':'相对强弱指标，衡量近期上涨与下跌动能；高位可能超买，低位可能超卖，但不能单独构成交易依据。',
  'MACD':'指数均线差与信号线，用于观察趋势动能和交叉变化。',
  'BOS':'Break of Structure，价格突破已确认结构高点或低点。',
  'CHoCH':'Change of Character，结构特征发生变化的早期提示。',
  'FVG':'Fair Value Gap，快速价格运动形成的未充分成交区间。',
  'Volume Ratio':'当前成交量相对 20 周期平均成交量的倍数。',
  'Impact Score':'新闻事件方向、幅度、关联资产和时效性的规则化影响分，不是价格预测。',
  'Risk Score':'根据波动率、极端动量与负面新闻计算的当前风险强度，分数越高风险越高。',
}
</script>
<template><span class="info-tip" tabindex="0">{{term}} <i>i</i><span class="info-pop">{{definitions[term]||'该指标来自当前系统真实数据和可审计规则。'}}</span></span></template>
