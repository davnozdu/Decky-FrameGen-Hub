const fs=require('fs'), vm=require('vm'), assert=require('assert'), ts=require('typescript'), path=require('path');
const output=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/steam.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
const custom='WINEDLLOVERRIDES="dxgi=n,b" STEAM_COMPAT_DATA_PATH="/prefix" %command% --exec="launch Fen"';
const changes=[];
const sandbox={exports:{},console,Promise,window:{setTimeout,clearTimeout,appStore:{allApps:[{appid:123,display_name:'Diablo IV',app_type:1073741824},{appid:456,display_name:'Native Steam game',app_type:1}]}},
 SteamClient:{Apps:{RegisterForAppDetails(id,cb){cb({strShortcutExe:'"/Battle.net Launcher.exe"',strShortcutStartDir:'"/"',strLaunchOptions:custom});return {unregister(){}}},SetAppLaunchOptions(id,options){changes.push({id,options})}}}};
vm.runInNewContext(output,sandbox);
(async()=>{
 const games=await sandbox.exports.getNonSteamShortcuts();
 assert.equal(games.length,1);assert.equal(games[0].appid,123);assert.equal(games[0].LaunchOptions,custom);
 assert.equal(await sandbox.exports.getLaunchOptions(123),custom);
 sandbox.exports.setLaunchOptions(123,custom+' --test');
 assert.deepEqual(changes,[{id:123,options:custom+' --test'}]);
 console.log('Live Steam metadata and launch option checks passed');
})().catch(e=>{console.error(e);process.exitCode=1});
