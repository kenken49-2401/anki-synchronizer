import {importPassword} from "./vault.mjs";
import {readStudyData, writeStudyData} from "./study-github-storage.mjs";
const config={owner:"kenken49-2401",repo:"anki-synchronizer",branch:"prototype/study-data",path:"study-data/study.enc.json"};
const q=s=>document.querySelector(s), status=t=>q("#cloudStatus").textContent=t;
let key=null,token=null,sha=null,ready=false;
q("#cloudConnect").onclick=async()=>{
  ready=false;key=null;token=null;
  try{
    const entered=q("#cloudToken").value.trim(), password=q("#cloudPassword").value;
    const newKey=await importPassword(password);
    status("GitHub のデータを確認しています…");
    const result=await readStudyData(config,entered,newKey);
    if(result.found){
      if(!window.studyBridge.valid(result.data)) throw Error("保存データの形式が正しくありません。");
      if(!confirm("GitHub のデータで、この端末の記録を置き換えますか？")){status("接続を取り消しました。");return}
      if(!window.studyBridge.replace(result.data)) throw Error("端末内に保存できませんでした。");
    }
    token=entered;key=newKey;sha=result.sha;ready=true;
    q("#cloudToken").value="";q("#cloudPassword").value="";
    status(result.found?"GitHub から読み込みました。「GitHubに保存」で変更を送れます。":"GitHub に保存データはまだありません。「GitHubに保存」でこの端末の記録を送れます。");
  }catch(e){status(e.message||"接続できませんでした。")}
};
q("#cloudSave").onclick=async()=>{
  if(!ready){status("先に GitHub に接続してください。");return}
  try{
    status("暗号化して GitHub に保存しています…");
    const d=window.studyBridge.get();
    sha=await writeStudyData(config,token,key,{...d,schema_version:1},sha);
    status("GitHub に暗号化して保存しました。");
  }catch(e){status(e.message||"保存できませんでした。")}
};
q("#cloudDisconnect").onclick=()=>{token=null;key=null;sha=null;ready=false;q("#cloudToken").value="";q("#cloudPassword").value="";status("接続を解除しました。")};
