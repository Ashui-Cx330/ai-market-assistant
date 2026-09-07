<script setup lang="ts">
import * as echarts from 'echarts'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Candle, IndicatorSet } from './api'
const props=defineProps<{candles:Candle[];indicators:IndicatorSet|null;structure?:any;news?:any[]}>()
const root=ref<HTMLDivElement>();let chart:echarts.ECharts|null=null
function values(key:string){return props.indicators?.series.map(x=>x[key]??'-')||[]}
function render(){
  if(!root.value||!props.candles.length)return
  chart??=echarts.init(root.value)
  const labels=props.candles.map(x=>x.timestamp.replace('T',' ').slice(0,16))
  const volume=props.candles.map(x=>({value:x.volume,itemStyle:{color:x.close>=x.open?'#22c99788':'#f15b7288'}}))
  const technical=props.structure
  const structureEvents=(technical?.structure?.events||[]).slice(-20)
  const marks:any[]=structureEvents.map((event:any)=>({
    name:event.type,value:event.type,
    coord:[event.break_time?.replace('T',' ').slice(0,16),event.break_price],
    itemStyle:{color:event.direction==='BULLISH'?'#22c997':'#f15b72'},
    label:{color:'#fff',formatter:`${event.type}\n${event.direction}`}
  }))
  const firstTime=Date.parse(props.candles[0].timestamp),lastTime=Date.parse(props.candles[props.candles.length-1].timestamp)
  for(const item of props.news||[]){
    const stamp=Date.parse(item.published_at||'')
    if(!Number.isFinite(stamp)||stamp<firstTime||stamp>lastTime)continue
    let index=0,best=Infinity
    props.candles.forEach((bar,i)=>{const distance=Math.abs(Date.parse(bar.timestamp)-stamp);if(distance<best){best=distance;index=i}})
    marks.push({name:'新闻',value:item.event?.event_type||'新闻',coord:[labels[index],props.candles[index].close],symbol:'pin',symbolSize:48,
      itemStyle:{color:(item.sentiment?.score||0)>=0?'#22c997':'#f15b72'},label:{color:'#fff',formatter:'新闻'}})
  }
  const fibLines:any[]=Object.entries(technical?.fibonacci?.levels||{})
    .filter(([ratio])=>['0.382','0.5','0.618','0.786','1.272','1.618'].includes(ratio))
    .map(([ratio,value])=>({name:`Fib ${ratio}`,yAxis:value as number,label:{formatter:`Fib ${ratio}`},lineStyle:{type:'dashed',width:1,color:'#b48cff88'}}))
  const plan=technical?.risk_plan
  if(plan){
    fibLines.push({name:'Entry',yAxis:plan.entry,label:{formatter:'Entry'},lineStyle:{type:'solid',width:1,color:'#36d6c4'}} as any)
    fibLines.push({name:'Stop',yAxis:plan.stop_loss,label:{formatter:'Stop'},lineStyle:{type:'solid',width:1,color:'#f15b72'}} as any)
    for(const target of plan.take_profits||[])fibLines.push({name:target.name,yAxis:target.price,label:{formatter:target.name},lineStyle:{type:'dotted',width:1,color:'#f0b95c'}} as any)
  }
  fibLines.push({name:'实时价',yAxis:props.candles[props.candles.length-1].close,label:{formatter:'实时 {c}'},lineStyle:{type:'solid',width:1,color:'#36d6c4aa'}} as any)
  const fvgAreas:any[]=(technical?.fvgs||[]).filter((gap:any)=>gap.status!=='FILLED').slice(-6).map((gap:any)=>[
    {name:`${gap.direction} FVG`,xAxis:gap.creation_time?.replace('T',' ').slice(0,16),yAxis:gap.bottom,itemStyle:{color:gap.direction==='BULLISH'?'#22c99718':'#f15b7218'}},
    {xAxis:labels[labels.length-1],yAxis:gap.top}
  ])
  const option:echarts.EChartsOption={
    animation:false,backgroundColor:'transparent',
    tooltip:{trigger:'axis',axisPointer:{type:'cross'},backgroundColor:'#0b1725',borderColor:'#2a425b',textStyle:{color:'#dbe8f5'}},
    legend:{data:['K线','MA5','MA10','MA20','MA60','EMA12','EMA26','VWAP','成交量'],textStyle:{color:'#7890a8'},top:4},
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
      {name:'K线',type:'candlestick',data:props.candles.map(x=>[x.open,x.close,x.low,x.high]),itemStyle:{color:'#22c997',color0:'#f15b72',borderColor:'#22c997',borderColor0:'#f15b72'},
       markPoint:{symbolSize:42,data:marks},markLine:{symbol:'none',silent:true,data:fibLines},markArea:{silent:true,data:fvgAreas}},
      {name:'MA5',type:'line',data:values('ma5'),smooth:true,showSymbol:false,lineStyle:{width:1.4,color:'#f0b95c'}},
      {name:'MA10',type:'line',data:values('ma10'),smooth:true,showSymbol:false,lineStyle:{width:1,color:'#b48cff'}},
      {name:'MA20',type:'line',data:values('ma20'),smooth:true,showSymbol:false,lineStyle:{width:1.4,color:'#4da3ff'}},
      {name:'MA60',type:'line',data:values('ma60'),smooth:true,showSymbol:false,lineStyle:{width:1,color:'#f15b72aa'}},
      {name:'EMA12',type:'line',data:values('ema12'),smooth:true,showSymbol:false,lineStyle:{width:1,type:'dashed',color:'#25d9c0'}},
      {name:'EMA26',type:'line',data:values('ema26'),smooth:true,showSymbol:false,lineStyle:{width:1,type:'dashed',color:'#e58d48'}},
      {name:'VWAP',type:'line',data:values('vwap'),smooth:true,showSymbol:false,lineStyle:{width:1.2,color:'#ffffff88'}},
      {name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:volume}
    ]
  }
  chart.setOption(option,true)
}
const resize=()=>chart?.resize();onMounted(()=>{nextTick(render);window.addEventListener('resize',resize)});watch(()=>[props.candles,props.indicators,props.structure,props.news],()=>nextTick(render),{deep:true});onBeforeUnmount(()=>{window.removeEventListener('resize',resize);chart?.dispose()})
</script>
<template><div ref="root" class="kline-chart"></div></template>
