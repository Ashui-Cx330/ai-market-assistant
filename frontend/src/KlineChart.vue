<script setup lang="ts">
import * as echarts from 'echarts'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Candle, IndicatorSet } from './api'
const props=defineProps<{candles:Candle[];indicators:IndicatorSet|null}>()
const root=ref<HTMLDivElement>();let chart:echarts.ECharts|null=null
function values(key:string){return props.indicators?.series.map(x=>x[key]??'-')||[]}
function render(){
  if(!root.value||!props.candles.length)return
  chart??=echarts.init(root.value)
  const labels=props.candles.map(x=>x.timestamp.replace('T',' ').slice(0,16))
  const volume=props.candles.map(x=>({value:x.volume,itemStyle:{color:x.close>=x.open?'#22c99788':'#f15b7288'}}))
  const option:echarts.EChartsOption={
    animation:false,backgroundColor:'transparent',
    tooltip:{trigger:'axis',axisPointer:{type:'cross'},backgroundColor:'#0b1725',borderColor:'#2a425b',textStyle:{color:'#dbe8f5'}},
    legend:{data:['K线','MA5','MA20','成交量'],textStyle:{color:'#7890a8'},top:4},
    grid:[{left:54,right:22,top:38,height:'58%'},{left:54,right:22,top:'74%',height:'14%'}],
    xAxis:[
      {type:'category',data:labels,boundaryGap:true,axisLine:{lineStyle:{color:'#31465d'}},axisLabel:{color:'#637991'}},
      {type:'category',gridIndex:1,data:labels,axisLabel:{show:false},axisLine:{lineStyle:{color:'#31465d'}}}
    ],
    yAxis:[
      {scale:true,axisLabel:{color:'#637991'},splitLine:{lineStyle:{color:'#17283a'}}},
      {gridIndex:1,scale:true,axisLabel:{color:'#637991'},splitLine:{show:false}}
    ],
    dataZoom:[
      {type:'inside',xAxisIndex:[0,1],start:55,end:100},
      {type:'slider',xAxisIndex:[0,1],bottom:2,height:18,borderColor:'#24394f',fillerColor:'#1a5f6655',textStyle:{color:'#60768e'}}
    ],
    series:[
      {name:'K线',type:'candlestick',data:props.candles.map(x=>[x.open,x.close,x.low,x.high]),itemStyle:{color:'#22c997',color0:'#f15b72',borderColor:'#22c997',borderColor0:'#f15b72'}},
      {name:'MA5',type:'line',data:values('ma5'),smooth:true,showSymbol:false,lineStyle:{width:1.4,color:'#f0b95c'}},
      {name:'MA20',type:'line',data:values('ma20'),smooth:true,showSymbol:false,lineStyle:{width:1.4,color:'#4da3ff'}},
      {name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:volume}
    ]
  }
  chart.setOption(option,true)
}
const resize=()=>chart?.resize();onMounted(()=>{nextTick(render);window.addEventListener('resize',resize)});watch(()=>[props.candles,props.indicators],()=>nextTick(render),{deep:true});onBeforeUnmount(()=>{window.removeEventListener('resize',resize);chart?.dispose()})
</script>
<template><div ref="root" class="kline-chart"></div></template>
