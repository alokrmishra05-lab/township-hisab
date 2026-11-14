'use strict';
/* सूर्य कुंज - साइट खर्च | Supabase Auth + RLS + निजी Storage */
(() => {
  const $ = id => document.getElementById(id);
  const cfg = window.SITE_EXPENSE_CONFIG || {};
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;':'&quot;',"'":'&#39;'}[c]));
  const money = n => '₹' + Number(n).toLocaleString('en-IN',{minimumFractionDigits:0,maximumFractionDigits:2});
  const statusName = {pending:'जाँच बाकी',approved:'स्वीकृत',rejected:'अस्वीकृत'};
  const bucket = 'site-expense-evidence';
  const mime = new Set(['image/jpeg','image/png','image/webp','application/pdf','application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document']);
  const allowedPayers = new Set(['गगन आचारी','अमरनाथ पाण्डेय','आलोक रंजन मिश्र','परियोजना फंड','साइट कैश']);
  let db, user, member, busy = false;
  const show = (message,type='') => {
    $('message').hidden = false;
    $('message').className = 'notice ' + type;
    $('message').textContent = message;
  };
  const error = e => String(e?.message || e || 'अज्ञात त्रुटि');
  const setBusy = value => {
    busy = value;
    ['loginBtn','submitBtn','refreshBtn'].forEach(id => { if($(id)) $(id).disabled = value; });
  };
  const validConfig = /^https:\/\/[a-z0-9-]+\.supabase\.co\/?$/i.test(cfg.url||'')
    && typeof cfg.anonKey === 'string' && cfg.anonKey.length > 40;
  if (!validConfig || !window.supabase?.createClient) {
    $('setup').hidden = false;
    if (validConfig) $('setup').textContent = 'ऑनलाइन सेवा लोड नहीं हुई। नेटवर्क की जाँच कर फिर खोलें।';
    return;
  }
  db = window.supabase.createClient(cfg.url,cfg.anonKey,{
    auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:false}
  });

  const localDate = () => {
    const d = new Date(), z = n => String(n).padStart(2,'0');
    return [d.getFullYear(),z(d.getMonth()+1),z(d.getDate())].join('-');
  };
  $('date').value = localDate();

  async function refreshSession(){
    const {data:{user:current},error:e} = await db.auth.getUser();
    if(e && !/session missing/i.test(error(e))) show(error(e),'error');
    user = current || null;
    member = null;
    if(user){
      const {data,error:memberError} = await db.from('site_expense_members')
        .select('role,display_name,active').eq('user_id',user.id).maybeSingle();
      if(memberError) show('सदस्यता नहीं पढ़ सके: '+error(memberError),'error');
      if(data?.active && ['admin','partner','assistant'].includes(data.role)) member=data;
    }
    $('signOut').hidden = !user;
    $('loginBox').hidden = !!user;
    $('workspace').hidden = !member;
    if(user && !member) show('अकाउंट लॉगिन है, लेकिन साइट खर्च की अनुमति नहीं मिली। व्यवस्थापक से सदस्यता जोड़ने को कहें।','error');
    if(member){
      $('identity').textContent = member.display_name + ' · ' +
        ({admin:'व्यवस्थापक',partner:'साझेदार',assistant:'साइट असिस्टेंट'}[member.role]);
      await loadExpenses();
    }
  }
  $('loginForm').addEventListener('submit',async e=>{
    e.preventDefault(); if(busy)return; setBusy(true);
    try {
      const {error:e} = await db.auth.signInWithPassword({
        email:$('email').value.trim(), password:$('password').value
      });
      if(e)throw e;
      $('password').value='';
      $('message').hidden=true;
      await refreshSession();
    } catch(e){show('लॉगिन नहीं हुआ: '+error(e),'error');}
    finally{setBusy(false);}
  });
  $('signOut').addEventListener('click',async()=>{
    const {error:e} = await db.auth.signOut();
    if(e)show('लॉगआउट असफल: '+error(e),'error');
    else {user=null;member=null;$('workspace').hidden=true;await refreshSession();}
  });
  const validateFiles = files => {
    if(!files.length || files.length>5) throw Error('1 से 5 प्रमाण फ़ाइलें चुनें।');
    for(const f of files){
      if(!mime.has(f.type))throw Error('यह फ़ाइल प्रकार मान्य नहीं है: '+f.name);
      if(f.size===0 || f.size>10*1024*1024)throw Error('फ़ाइल का आकार 1 byte से 10 MB तक होना चाहिए: '+f.name);
    }
  };
  $('expenseForm').addEventListener('submit',async e=>{
    e.preventDefault();if(busy || !member || !user)return;
    const files=Array.from($('proof').files);
    let inserted=null;
    try{
      validateFiles(files);
      const amt=Number($('amount').value);
      if(!Number.isFinite(amt) || amt<=0 || amt>100000000)throw Error('सही राशि भरें।');
      if(!allowedPayers.has($('payer').value))throw Error('पैसे देने वाले का नाम चुनें।');
      const fields = {
        incurred_on:$('date').value,
        category:$('category').value,
        description:$('description').value.trim(),
        amount:amt,
        paid_by:$('payer').value,
        payment_method:$('method').value,
        bill_no:$('bill').value.trim()||null,
        note:$('note').value.trim()||null
      };
      if(!fields.incurred_on || !fields.category || !fields.description)throw Error('आवश्यक विवरण भरें।');
      setBusy(true);
      const {data,error:insertError}=await db.from('site_expenses')
        .insert(fields).select('id').single();
      if(insertError)throw insertError;
      inserted=data.id;
      let count=0;
      for(const file of files){
        const suffix=(file.name.split('.').pop()||'file').replace(/[^a-zA-Z0-9]/g,'').slice(0,10).toLowerCase();
        const path=user.id+'/'+inserted+'/'+crypto.randomUUID()+(suffix?'.'+suffix:'');
        const {error:uploadError}=await db.storage.from(bucket).upload(path,file,{
          cacheControl:'3600',upsert:false,contentType:file.type
        });
        if(uploadError)throw Error('प्रमाण अपलोड असफल: '+error(uploadError));
        const {error:metaError}=await db.from('site_expense_evidence').insert({
          expense_id:inserted,storage_path:path,original_filename:file.name.slice(0,255),
          mime_type:file.type,size_bytes:file.size
        });
        if(metaError)throw Error('फ़ाइल चढ़ गई, लेकिन रिकॉर्ड लिंक नहीं हुआ: '+error(metaError));
        count++;
      }
      $('expenseForm').reset();$('date').value=localDate();
      show('खर्च दर्ज हुआ। '+count+' प्रमाण फ़ाइलें सुरक्षित हुईं। अब व्यवस्थापक की मंज़ूरी बाकी है।','success');
      await loadExpenses();
    }catch(e){
      show((inserted?'खर्च Pending में दर्ज हो गया है, लेकिन प्रमाण का अपलोड अधूरा है। व्यवस्थापक से एंट्री '+inserted+' की जाँच कराएँ। ':'')+error(e),'error');
      if(inserted)await loadExpenses();
    }finally{setBusy(false);}
  });
  $('refreshBtn').addEventListener('click',()=>{if(!busy)loadExpenses();});
  async function loadExpenses(){
    const {data,error:e} = await db.from('site_expenses')
      .select('id,incurred_on,category,description,amount,paid_by,payment_method,bill_no,note,status,created_at,review_note,submitted_by')
      .order('created_at',{ascending:false}).limit(200);
    if(e){show('रिकॉर्ड नहीं मिला: '+error(e),'error');return;}
    const records=data||[];
    const ids=records.map(v=>v.id);
    const {data:proofs,error:proofError}=ids.length?await db.from('site_expense_evidence')
      .select('expense_id,storage_path,original_filename').in('expense_id',ids):
      {data:[],error:null};
    if(proofError){show('प्रमाण सूची नहीं खुली: '+error(proofError),'error');return;}
    const byExpense=new Map();
    (proofs||[]).forEach(p=>{
      if(!byExpense.has(p.expense_id))byExpense.set(p.expense_id,[]);
      byExpense.get(p.expense_id).push(p);
    });
    const approved=records.filter(r=>r.status==='approved').reduce((s,r)=>s+Number(r.amount),0);
    const pending=records.filter(r=>r.status==='pending').reduce((s,r)=>s+Number(r.amount),0);
    $('totals').textContent='स्वीकृत साइट खर्च: '+money(approved)+' · समीक्षा बाकी: '+money(pending)+' · पिछली 200 एंट्री';
    if(!records.length){$('entries').textContent='अभी कोई साइट खर्च दर्ज नहीं हुआ।';return;}
    $('entries').innerHTML=records.map(r=>{
      const ev=byExpense.get(r.id)||[];
      const badgeClass=r.status==='approved'?'ok':r.status==='rejected'?'no':'';
      const evidence=ev.length?ev.map(p=>'<button type="button" class="secondary proofBtn" data-path="'+esc(p.storage_path)+'">'+esc(p.original_filename)+'</button>').join(' '):'<small>प्रमाण संलग्न नहीं है</small>';
      const reviews=member.role==='admin' && r.status==='pending'
        ? '<div class="row" style="margin-top:10px"><button type="button" class="approveBtn" data-id="'+esc(r.id)+'" '+(!ev.length?'disabled title="प्रमाण आवश्यक"':'')+'>स्वीकृत करें</button><button type="button" class="secondary rejectBtn" data-id="'+esc(r.id)+'">अस्वीकृत करें</button></div>' : '';
      return '<div class="item"><div class="row" style="align-items:center"><span class="label-text">'+esc(r.category)+'</span><span class="amount">'+money(r.amount)+'</span></div>'+
        '<span class="badge '+badgeClass+'">'+esc(statusName[r.status]||r.status)+'</span> <small style="display:inline">'+esc(r.incurred_on)+' · भुगतान: '+esc(r.paid_by)+'</small>'+
        '<p style="margin:8px 0">'+esc(r.description)+'</p>'+
        '<small>माध्यम: '+esc(r.payment_method)+(r.bill_no?' · बिल: '+esc(r.bill_no):'')+'</small>'+
        (r.note?'<small>टिप्पणी: '+esc(r.note)+'</small>':'')+
        (r.review_note?'<small>समीक्षा: '+esc(r.review_note)+'</small>':'')+
        '<div class="row" style="margin-top:9px">'+evidence+'</div>'+reviews+'</div>';
    }).join('');
    document.querySelectorAll('.proofBtn').forEach(b=>b.addEventListener('click',async()=>{
      const path=b.dataset.path; b.disabled=true;
      try{
        const {data,error:e}=await db.storage.from(bucket).createSignedUrl(path,60);
        if(e)throw e;
        window.open(data.signedUrl,'_blank','noopener,noreferrer');
      }catch(e){show('प्रमाण नहीं खुला: '+error(e),'error');}
      finally{b.disabled=false;}
    }));
    document.querySelectorAll('.approveBtn,.rejectBtn').forEach(b=>b.addEventListener('click',async()=>{
      if(busy)return;
      const approve=b.classList.contains('approveBtn');
      const note=approve?null:window.prompt('अस्वीकृति का कारण लिखें (अधिकतम 500 अक्षर):');
      if(!approve && (!note || !note.trim()))return;
      if(note && note.length>500){show('कारण 500 अक्षर से छोटा रखें','error');return;}
      if(approve && !window.confirm('क्या आप यह खर्च मंज़ूर करना चाहते हैं?'))return;
      setBusy(true);
      try{
        const {error:e}=await db.rpc('review_site_expense',{
          p_expense_id:b.dataset.id,p_approve:approve,p_note:note||null
        });
        if(e)throw e;
        show('समीक्षा दर्ज हुई।','success');
        await loadExpenses();
      }catch(e){show('समीक्षा असफल: '+error(e),'error');}
      finally{setBusy(false);}
    }));
  }
  refreshSession().catch(e=>show('सेवा से संपर्क नहीं हो पाया: '+error(e),'error'));
})();