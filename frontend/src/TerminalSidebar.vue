<script setup lang="ts">
defineProps<{page:string;version:string}>()
const emit=defineEmits<{(e:'navigate',page:string):void}>()
const groups=[
  {label:'01 · 工作台',items:[['home','◧','市场总览'],['briefing','◈','交易决策台'],['watchlist','☆','我的自选']]},
  {label:'02 · 市场',items:[['cnMarket','沪','A股行情'],['usMarket','美','美股行情'],['cryptoMarket','币','热门币种']]},
  {label:'03 · 预测与证据',items:[['prediction','◎','走势预测'],['screener','⌕','智能选股'],['news','◉','新闻情报'],['quantResearch','∑','量化研究'],['modelLab','◫','模型表现']]},
  {label:'04 · 验证与模拟',items:[['strategy','⌘','策略实验室'],['backtest','↗','历史回测'],['paper','▣','模拟交易']]},
  {label:'05 · 系统',items:[['copilot','✦','AI 市场助手'],['settings','⚙','设置与数据健康']]},
]
</script>
<template>
  <aside class="terminal-sidebar">
    <div class="brand"><div class="logo">A</div><div><b>AI行情助手</b><small>QUANT STUDIO · v{{version}}</small></div></div>
    <nav>
      <section v-for="group in groups" :key="group.label">
        <label>{{group.label}}</label>
        <button v-for="item in group.items" :key="item[0]" :class="{active:page===item[0]}" @click="emit('navigate',item[0])">
          <i>{{item[1]}}</i><span>{{item[2]}}</span>
        </button>
      </section>
    </nav>
    <div class="research-note"><b>● 研究模式</b><span>预测须经过样本外验证；未达标时仅供观察。</span></div>
  </aside>
</template>
