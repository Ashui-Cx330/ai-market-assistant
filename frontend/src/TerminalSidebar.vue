<script setup lang="ts">
defineProps<{page:string;version:string}>()
const emit=defineEmits<{(e:'navigate',page:string):void}>()
const groups=[
  {label:'市场',items:[['home','⌂','首页'],['market','⌁','行情'],['watchlist','☆','自选']]},
  {label:'AI 分析',items:[['screener','⌕','AI 选股'],['prediction','◎','AI 预测'],['modelLab','◫','模型表现'],['news','◉','新闻情报']]},
  {label:'策略',items:[['strategy','⌘','策略实验室'],['backtest','↗','回测']]},
  {label:'交易',items:[['paper','▣','模拟交易']]},
  {label:'AI',items:[['copilot','✦','AI Copilot']]},
  {label:'系统',items:[['settings','⚙','设置']]},
]
</script>
<template>
  <aside class="terminal-sidebar">
    <div class="brand"><div class="logo">AI</div><div><b>AI行情助手</b><small>Terminal v{{version}}</small></div></div>
    <nav>
      <section v-for="group in groups" :key="group.label">
        <label>{{group.label}}</label>
        <button v-for="item in group.items" :key="item[0]" :class="{active:page===item[0]}" @click="emit('navigate',item[0])">
          <i>{{item[1]}}</i><span>{{item[2]}}</span>
        </button>
      </section>
    </nav>
    <div class="research-note"><b>研究与模拟模式</b><span>概率评分与回测不构成投资建议。</span></div>
  </aside>
</template>
