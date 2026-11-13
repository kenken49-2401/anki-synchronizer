import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../web/study-atlas.html',import.meta.url),'utf8');
const helpers=['function goalLines(','function scoreGoalColors(','function drawGoalBands(','function lineChart('].map(key=>{
    const start=source.indexOf(key);
    assert(start>=0,key);
    return source.slice(start,source.indexOf('\n',start));
}).join('\n');

function chart(theme,width,values){
    const strokes=[],labels=[],fills=[];
    const context=new Proxy({lineWidth:1,measureText(text){return {width:String(text).length*6}},stroke(){strokes.push({color:this.strokeStyle,width:this.lineWidth,join:this.lineJoin,cap:this.lineCap})},fillText(text,x,y){labels.push({text,x,y})},fillRect(){fills.push(this.fillStyle)}},{get(target,key){return key in target?target[key]:()=>{}}});
    const canvas={clientWidth:width,getContext:()=>context};
    const draw=new Function('canvas','values','chartColor','getComputedStyle','devicePixelRatio','setupChartTooltip',helpers+";lineChart(canvas,values.map((_,i)=>'2026-10-'+String(i+1).padStart(2,'0')),values,60,[],{floor:24,target:36,ideal:48});return scoreGoalColors()");
    const colors=draw(canvas,values,(light,dark)=>theme==='dark'?dark:light,()=>({getPropertyValue:()=> '#e4954b'}),2,()=>{});
    return {strokes,labels,fills,colors};
}

test('sharp score reversals use a single round subject stroke at mobile and desktop widths',()=>{
    for(const theme of ['dark','light'])for(const width of [320,390,1100]){
        const {strokes,labels}=chart(theme,width,Array.from({length:24},(_,i)=>i%2?55:8));
        const line=strokes.filter(x=>x.color==='#e4954b');
        assert.equal(line.length,1);
        assert.deepEqual(line[0],{color:'#e4954b',width:2,join:'round',cap:'round'});
        assert(strokes.every(x=>x.width<=2));
        const dates=labels.filter(x=>String(x.text).startsWith('26/'));
        assert.equal(dates[0].text,'26/10/01');
        assert.equal(dates.at(-1).text,'26/10/24');
        for(let i=1;i<dates.length;i++)assert(dates[i].x-dates[i-1].x>=70,'date labels need room between them');
    }
});

test('goal bands share their palette and preserve light colors',()=>{
    const dark=chart('dark',390,[8,55]);
    assert.deepEqual(dark.fills,Object.values(dark.colors));
    const light=chart('light',390,[8,55]);
    assert.deepEqual(light.fills,['#f8d6d6','#ffedbf','#d6efdb','#d6eaff']);
    // Every built-in subject remains discernible against each dark goal band.
    const luminance=hex=>{const rgb=hex.match(/[a-f\d]{2}/gi).map(x=>parseInt(x,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return rgb.reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0)};
    const subjects=source.match(/const studyColors=\{([^}]+)\}/)[1].match(/#[a-f\d]{6}/gi);
    for(const subject of subjects)for(const band of dark.fills)assert((luminance(subject)+.05)/(luminance(band)+.05)>=3);
});

test('empty and single score charts render without invalid date positions',()=>{
    for(const values of [[],[30]]){
        const {labels}=chart('dark',390,values);
        assert(labels.every(x=>Number.isFinite(x.x)&&Number.isFinite(x.y)));
    }
});
