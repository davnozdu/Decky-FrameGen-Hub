const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const js=ts.transpileModule(fs.readFileSync('src/focus.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
function setup(){
 const events={},timers=new Map();let id=0,node;
 const document={activeElement:null,addEventListener:(name,fn)=>events[name]=fn,removeEventListener:name=>delete events[name]};
 const scroll={isConnected:true,scrollHeight:1000,clientHeight:300,scrollTop:350,scrollLeft:0,parentElement:null};
 function field(label){return {label,isConnected:true,parentElement:scroll,scrollHeight:30,clientHeight:30,scrollTop:0,scrollLeft:0,focusCalls:[],getAttribute:key=>key==='aria-label'?label:null,focus(options){this.focusCalls.push(options);document.activeElement=this}}}
 const a=field('A'),b=field('B'),menu=field('outside-menu');
 const root={isConnected:true,ownerDocument:document,contains:el=>el===a||el===b,querySelectorAll:()=>[a,b]};
 let nativeCalls=0;
 const nav=element=>({Element:element,TakeFocus(){nativeCalls++;document.activeElement=element;node=this}});
 node=nav(a);document.activeElement=a;
 const exports={};vm.runInNewContext(js,{exports,require:()=>({getFocusNavController:()=>({GetActiveContext:()=>({m_LastActiveFocusNavTree:{GetLastFocusedNode:()=>node}})})}),setTimeout:fn=>{timers.set(++id,fn);return id},clearTimeout:key=>timers.delete(key)});
 const cleanup=exports.registerFocusRoot(root);
 return {api:exports,a,b,menu,scroll,events,timers,cleanup,native:()=>nativeCalls,setActive:el=>{node=nav(el);document.activeElement=el},flush(){for(const fn of [...timers.values()])fn();timers.clear()}};
}
(async()=>{
 let s=setup();await s.api.withSettingFocus(async()=>{s.scroll.scrollTop=900;s.setActive(s.b)})();s.flush();
 assert.equal(s.scroll.scrollTop,350);assert(s.native()>0);assert.equal(s.a.focusCalls[0].preventScroll,true);
 s=setup();s.api.openMenuWithFocus(()=>s.setActive(s.menu));await s.api.withSettingFocus(async()=>{s.scroll.scrollTop=990})();s.flush();assert(s.a.focusCalls.length>0);assert.equal(s.menu.focusCalls.length,0);assert.equal(s.scroll.scrollTop,350);
 s=setup();await s.api.withSettingFocus(async()=>{s.events.keydown();s.scroll.scrollTop=700})();s.flush();assert.equal(s.a.focusCalls.length,0);assert.equal(s.scroll.scrollTop,700);
 s=setup();let finish;const first=s.api.withSettingFocus(()=>new Promise(r=>finish=r))();s.setActive(s.b);s.scroll.scrollTop=450;await s.api.withSettingFocus(async()=>{s.scroll.scrollTop=999})();finish();await first;s.flush();assert.equal(s.a.focusCalls.length,0);assert(s.b.focusCalls.length>0);assert.equal(s.scroll.scrollTop,450);
 s=setup();await s.api.withSettingFocus(async()=>{})();s.cleanup();s.flush();assert.equal(s.a.focusCalls.length,0);
 s=setup();await assert.rejects(s.api.withSettingFocus(async()=>{s.scroll.scrollTop=999;throw Error('save failed')})());s.flush();assert(s.a.focusCalls.length>0);assert.equal(s.scroll.scrollTop,350);
 const source=fs.readFileSync('src/index.tsx','utf8'),tree=ts.createSourceFile('i.tsx',source,99,true,4);const protectedNames=new Set(['run','changeGenerator','changeSetting','changeUpscaler','changeOpti','profileAction','changeRenderQuality']);
 function check(n){if(ts.isVariableDeclaration(n)&&protectedNames.has(n.name.getText(tree))){assert(ts.isCallExpression(n.initializer)&&n.initializer.expression.getText(tree)==='withSettingFocus',n.name.getText(tree));protectedNames.delete(n.name.getText(tree));}ts.forEachChild(n,check)}check(tree);assert.equal(protectedNames.size,0);
 console.log('Focus checks passed: Steam + DOM focus, menu origins, scroll position, newer changes, user navigation, unmount and failed saves.');
})().catch(e=>{console.error(e);process.exitCode=1});
