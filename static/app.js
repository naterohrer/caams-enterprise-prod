/* CAAMS Enterprise — Alpine.js application */
function app() {
  return {

    /* ── State ───────────────────────────────────────────────────────── */
    view:'loading', sub:'overview',
    token: localStorage.getItem('caams_token'),
    refreshToken: localStorage.getItem('caams_refresh_token'),
    user:null, role:'viewer',
    toast:null, toastType:'success', _toastTimer:null,

    dash:null, assessments:[], assessment:null, results:null,
    controls:[], signoffs:[], evidence:[], findings:[], rfis:[],
    riskAcceptances:[], auditorShares:[], newShareToken:null,
    comments:[], inviteResult:null, auditorData:null, auditorCommentForm:{control_id:'',comment_text:''},
    multiFramework:null,
    assessmentLog:[], frameworks:[], frameworkControls:{},
    crosswalkSrc:null, crosswalkTgt:null, crosswalkData:null,
    tools:[], assessmentTools:[], auditLog:[], users:[], apiTokens:[], userDirectory:[],

    ctrlFilter:'', ctrlStatusFilter:'',
    modal:null, confirmMsg:'', confirmCb:null, newToken:null,
    f:{},
    _fwChart:null, _findChart:null,
    _auditorToken:null, _auditorAssessmentId:null,
    notifications:{rfis:[],findings:[],controls:[],total:0}, notifOpen:false, _notifTimer:null,
    ctrlExpanded:{}, fwCtrlExpanded:{},
    darkMode: localStorage.getItem('caams_dark')==='1',

    // MFA
    mfaPending: false, mfaToken: null, mfaCode: '',
    mfaSetup: null,    // {secret, otpauth_uri, qr_svg} from GET /auth/mfa/setup
    // SSO / OIDC
    oidcConfigured: false,
    oidcIssuer: null, oidcClientId: null, oidcDefaultRole: null, oidcCallbackUrl: null,
    oidcSource: 'none', oidcHasSecret: false,
    oidcEditMode: false, oidcSaving: false,
    oidcForm: { issuer: '', client_id: '', client_secret: '', default_role: 'viewer' },
    // SMTP
    smtpConfigured: false,
    smtpHost: null, smtpPort: null, smtpFrom: null, smtpUser: null, smtpTls: true,
    smtpSource: 'none', smtpHasPassword: false,
    smtpTestAddress: '',
    smtpEditMode: false, smtpSaving: false,
    smtpForm: { host: '', port: 587, from_addr: '', user: '', password: '', use_tls: true },
    // Backup
    backups: [], backupsConfigured: false,

    /* ── Init ────────────────────────────────────────────────────────── */
    async init() {
      this.initDarkMode();
      // Check URL params before anything else — handle share links and invite links
      const params = new URLSearchParams(window.location.search);
      const inviteToken = params.get('invite');
      const shareToken  = params.get('token');
      const shareId     = params.get('id');

      if (inviteToken) {
        this.f = {token: inviteToken, password: '', password2: ''};
        this.view = 'acceptInvite';
        return;
      }
      if (shareToken && shareId) {
        await this.loadAuditorView(shareId, shareToken);
        return;
      }

      try {
        const {needed} = await this.api('GET','/auth/setup-needed');
        if (needed){this.view='setup'; return;}
      } catch(_){}
      if (this.token) {
        try {
          const me = await this.api('GET','/auth/me');
          this.user=me; this.role=me.role;
          this.loadNotifications();
          this._notifTimer=setInterval(()=>this.loadNotifications(), 60000);
          await this.nav('dashboard'); return;
        } catch(_){
          this.token=null; localStorage.removeItem('caams_token');
        }
      }
      this.view='login';
      this.checkOIDCStatus();
    },

    initDarkMode() {
      document.documentElement.classList.toggle('dark', this.darkMode);
    },
    toggleDarkMode() {
      this.darkMode = !this.darkMode;
      localStorage.setItem('caams_dark', this.darkMode ? '1' : '0');
      this.initDarkMode();
    },

    async loadNotifications() {
      try {
        this.notifications=await this.api('GET','/auth/notifications/my');
      } catch(_){}
    },

    /* ── API helper ───────────────────────────────────────────────────── */
    async _fetch(method, path, body, isForm=false) {
      const headers={};
      if (this.token) headers['Authorization']='Bearer '+this.token;
      let bodyVal;
      if (body!=null) {
        if (isForm){bodyVal=body;}
        else{headers['Content-Type']='application/json'; bodyVal=JSON.stringify(body);}
      }
      return fetch(path,{method,headers,body:bodyVal});
    },

    async _tryRefresh() {
      if (!this.refreshToken) return false;
      try {
        const r=await fetch('/auth/refresh',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({refresh_token:this.refreshToken})});
        if (!r.ok) return false;
        const data=await r.json();
        this.token=data.access_token; this.refreshToken=data.refresh_token;
        localStorage.setItem('caams_token',this.token);
        localStorage.setItem('caams_refresh_token',this.refreshToken);
        return true;
      } catch(_){return false;}
    },

    async api(method, path, body, isForm=false) {
      let r=await this._fetch(method,path,body,isForm);
      if (r.status===401 && path!=='/auth/login' && path!=='/auth/refresh') {
        const ok=await this._tryRefresh();
        if (ok) { r=await this._fetch(method,path,body,isForm); }
        else { this.logout(); throw new Error('Session expired — please log in again'); }
      }
      if (r.status===204) return null;
      // Guard against non-JSON bodies (e.g. plain-text 429 from the rate limiter).
      let data;
      try { data=await r.json(); }
      catch(_) {
        if (r.status===429) throw new Error('Too many requests — please wait a moment and try again');
        throw new Error(`Request failed (${r.status})`);
      }
      if (!r.ok) {
        // FastAPI validation errors return detail as an array; flatten to a string.
        const msg=Array.isArray(data.detail)
          ? data.detail.map(e=>e.msg||JSON.stringify(e)).join('; ')
          : (data.detail||'Request failed');
        throw new Error(msg);
      }
      return data;
    },

    notify(msg, type='success') {
      clearTimeout(this._toastTimer);
      this.toast=msg; this.toastType=type;
      this._toastTimer=setTimeout(()=>this.toast=null, 4500);
    },

    fmt(d){if(!d)return'—'; return new Date(d).toLocaleDateString('en-US',{year:'numeric',month:'short',day:'numeric'});},
    fmtDt(d){if(!d)return'—'; return new Date(d).toLocaleString('en-US',{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});},
    formatBytes(n){if(!n)return'0 B';const u=['B','KB','MB','GB'];let i=0,v=n;while(v>=1024&&i<3){v/=1024;i++;}return v.toFixed(1)+' '+u[i];},
    fmtDetails(d){if(!d||!Object.keys(d).length)return'—'; return Object.entries(d).map(([k,v])=>k+': '+v).join(' | ');},

    statusBadge(s) {
      const m={
        draft:'bg-gray-100 text-gray-600',in_review:'bg-yellow-100 text-yellow-700',
        approved:'bg-green-100 text-green-700',archived:'bg-slate-100 text-slate-500',
        covered:'bg-green-100 text-green-700',partial:'bg-yellow-100 text-yellow-700',
        not_covered:'bg-red-100 text-red-700',not_applicable:'bg-gray-100 text-gray-500',
        open:'bg-red-100 text-red-700',in_progress:'bg-blue-100 text-blue-700',
        remediated:'bg-green-100 text-green-700',accepted:'bg-purple-100 text-purple-700',
        closed:'bg-gray-100 text-gray-500',responded:'bg-blue-100 text-blue-700',
        critical:'bg-red-200 text-red-800',high:'bg-orange-100 text-orange-700',
        medium:'bg-yellow-100 text-yellow-700',low:'bg-blue-100 text-blue-700',
        informational:'bg-gray-100 text-gray-500',
        not_reviewed:'bg-gray-100 text-gray-500',rejected:'bg-red-100 text-red-700',
        pending:'bg-yellow-100 text-yellow-700',active:'bg-green-100 text-green-700',
      };
      return m[s]||'bg-gray-100 text-gray-600';
    },

    /* ── Auth ────────────────────────────────────────────────────────── */
    async doSetup() {
      try {
        const r=await this.api('POST','/auth/setup',{username:this.f.username,password:this.f.password});
        this.token=r.access_token; this.refreshToken=r.refresh_token;
        localStorage.setItem('caams_token',this.token);
        localStorage.setItem('caams_refresh_token',this.refreshToken);
        this.role=r.role;
        this.user=await this.api('GET','/auth/me'); this.f={}; await this.nav('dashboard');
      } catch(e){this.notify(e.message,'error');}
    },

    async doLogin() {
      try {
        const fd=new FormData();
        fd.append('username',this.f.username||''); fd.append('password',this.f.password||'');
        const r=await this.api('POST','/auth/login',fd,true);
        if (r.mfa_required) {
          this.mfaPending=true; this.mfaToken=r.mfa_token; this.mfaCode=''; return;
        }
        this.token=r.access_token; this.refreshToken=r.refresh_token;
        localStorage.setItem('caams_token',this.token);
        localStorage.setItem('caams_refresh_token',this.refreshToken);
        this.role=r.role;
        this.user=await this.api('GET','/auth/me'); this.f={}; await this.nav('dashboard');
      } catch(e){this.notify(e.message,'error');}
    },

    async doMFAVerify() {
      try {
        const r=await this.api('POST','/auth/mfa/verify-login',{mfa_token:this.mfaToken,code:this.mfaCode});
        this.token=r.access_token; this.refreshToken=r.refresh_token;
        localStorage.setItem('caams_token',this.token);
        localStorage.setItem('caams_refresh_token',this.refreshToken);
        this.role=r.role; this.mfaPending=false; this.mfaToken=null; this.mfaCode='';
        this.user=await this.api('GET','/auth/me'); this.f={}; await this.nav('dashboard');
      } catch(e){this.notify(e.message,'error');}
    },

    async checkOIDCStatus() {
      try {
        const s = await this.api('GET', '/auth/oidc/status');
        this.oidcConfigured  = s.configured;
        this.oidcIssuer      = s.issuer       || null;
        this.oidcClientId    = s.client_id    || null;
        this.oidcDefaultRole = s.default_role || null;
        this.oidcCallbackUrl = s.callback_url || (window.location.origin + '/auth/oidc/callback');
      } catch(_) {}
    },

    async loadOidcConfig() {
      try {
        const s = await this.api('GET', '/admin/oidc/config');
        this.oidcConfigured  = s.configured;
        this.oidcIssuer      = s.issuer       || null;
        this.oidcClientId    = s.client_id    || null;
        this.oidcDefaultRole = s.default_role || 'viewer';
        this.oidcCallbackUrl = s.callback_url || (window.location.origin + '/auth/oidc/callback');
        this.oidcSource      = s.source       || 'none';
        this.oidcHasSecret   = s.has_secret   || false;
      } catch(_) {}
    },

    openOidcEdit() {
      this.oidcForm = {
        issuer:        this.oidcIssuer      || '',
        client_id:     this.oidcClientId    || '',
        client_secret: '',
        default_role:  this.oidcDefaultRole || 'viewer',
      };
      this.oidcEditMode = true;
    },

    async saveOidcConfig() {
      this.oidcSaving = true;
      try {
        const payload = { ...this.oidcForm };
        // Empty secret means "keep existing" — send null
        if (payload.client_secret === '') payload.client_secret = null;
        await this.api('PUT', '/admin/oidc/config', payload);
        await this.loadOidcConfig();
        this.oidcEditMode = false;
        this.notify('SSO settings saved');
      } catch(e) { this.notify(e.message, 'error'); }
      finally { this.oidcSaving = false; }
    },

    clearOidcConfig() {
      this.confirmDelete(
        'Clear saved SSO settings and revert to environment variables?',
        async () => {
          try {
            await this.api('DELETE', '/admin/oidc/config');
            await this.loadOidcConfig();
            this.oidcEditMode = false;
            this.notify('SSO settings cleared — using environment variables');
          } catch(e) { this.notify(e.message, 'error'); }
        }
      );
    },

    async testOidcConfig() {
      try {
        const r = await this.api('POST', '/admin/oidc/test');
        this.notify('Connection OK — discovery document fetched from ' + r.issuer);
      } catch(e) { this.notify(e.message, 'error'); }
    },

    initiateSSOLogin() { window.location.href='/auth/oidc/authorize'; },

    async loadSmtpStatus() {
      try {
        const s = await this.api('GET', '/admin/smtp/config');
        this.smtpConfigured  = s.configured;
        this.smtpHost        = s.host       || null;
        this.smtpPort        = s.port       || null;
        this.smtpFrom        = s.from_addr  || null;
        this.smtpUser        = s.user       || null;
        this.smtpTls         = s.use_tls;
        this.smtpSource      = s.source     || 'none';
        this.smtpHasPassword = s.has_password || false;
      } catch(_) {}
    },

    openSmtpEdit() {
      this.smtpForm = {
        host:      this.smtpHost     || '',
        port:      this.smtpPort     || 587,
        from_addr: this.smtpFrom     || '',
        user:      this.smtpUser     || '',
        password:  '',
        use_tls:   this.smtpTls,
      };
      this.smtpEditMode = true;
    },

    async saveSmtpConfig() {
      this.smtpSaving = true;
      try {
        const payload = { ...this.smtpForm };
        // Empty password field means "keep existing" — send null
        if (payload.password === '') payload.password = null;
        await this.api('PUT', '/admin/smtp/config', payload);
        await this.loadSmtpStatus();
        this.smtpEditMode = false;
        this.notify('SMTP settings saved');
      } catch(e) { this.notify(e.message, 'error'); }
      finally { this.smtpSaving = false; }
    },

    clearSmtpConfig() {
      this.confirmDelete(
        'Clear saved SMTP settings and revert to environment variables?',
        async () => {
          try {
            await this.api('DELETE', '/admin/smtp/config');
            await this.loadSmtpStatus();
            this.smtpEditMode = false;
            this.notify('SMTP settings cleared — using environment variables');
          } catch(e) { this.notify(e.message, 'error'); }
        }
      );
    },

    async sendSmtpTest() {
      try {
        await this.api('POST', '/admin/smtp/test', {to: this.smtpTestAddress});
        this.notify('Test email sent to ' + this.smtpTestAddress);
        this.smtpTestAddress = '';
      } catch(e) { this.notify(e.message, 'error'); }
    },

    async downloadBackup(filename) {
      try {
        const resp = await fetch(`/admin/backup/download/${encodeURIComponent(filename)}`, {
          headers: { Authorization: 'Bearer ' + this.token },
        });
        if (!resp.ok) { this.notify('Download failed', 'error'); return; }
        const blob = await resp.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      } catch(e) { this.notify('Download failed: ' + e.message, 'error'); }
    },

    /* ── MFA Setup (account settings) ───────────────────────────────── */
    async openMFASetup() {
      try { this.mfaSetup=await this.api('GET','/auth/mfa/setup'); this.modal='mfaSetup'; }
      catch(e){this.notify(e.message,'error');}
    },
    async confirmMFASetup() {
      try {
        await this.api('POST','/auth/mfa/confirm',{code:this.f.mfaCode||''});
        this.user=await this.api('GET','/auth/me');
        this.mfaSetup=null; this.modal=null; this.f={};
        this.notify('MFA enabled — your account is now protected');
      } catch(e){this.notify(e.message,'error');}
    },
    async disableMFA() {
      try {
        await this.api('POST','/auth/mfa/disable',{code:this.f.mfaCode||''});
        this.user=await this.api('GET','/auth/me');
        this.modal=null; this.f={};
        this.notify('MFA disabled');
      } catch(e){this.notify(e.message,'error');}
    },
    async adminResetMFA(userId) {
      try {
        await this.api('DELETE',`/auth/mfa/admin/${userId}`);
        this.users=await this.api('GET','/auth/users');
        this.notify('MFA reset for user');
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Backup ──────────────────────────────────────────────────────── */
    async loadBackups() {
      try {
        const d=await this.api('GET','/admin/backup/list');
        this.backups=d.backups||[]; this.backupsConfigured=d.configured;
      } catch(_){}
    },

    logout() {
      clearInterval(this._notifTimer);
      this.token=null; this.refreshToken=null;
      localStorage.removeItem('caams_token'); localStorage.removeItem('caams_refresh_token');
      this.user=null; this.role='viewer'; this.view='login'; this.f={};
      this.notifications={rfis:[],findings:[],controls:[],total:0}; this.notifOpen=false;
    },

    /* ── Accept Invite ───────────────────────────────────────────────── */
    async doAcceptInvite() {
      if (this.f.password !== this.f.password2) { this.notify('Passwords do not match','error'); return; }
      try {
        const r=await this.api('POST','/auth/invite/accept',{token:this.f.token,password:this.f.password});
        this.token=r.access_token; this.refreshToken=r.refresh_token;
        localStorage.setItem('caams_token',this.token);
        localStorage.setItem('caams_refresh_token',this.refreshToken);
        this.role=r.role;
        window.history.replaceState({},'',window.location.pathname);
        this.user=await this.api('GET','/auth/me'); this.f={};
        this.loadNotifications();
        this._notifTimer=setInterval(()=>this.loadNotifications(), 60000);
        await this.nav('dashboard');
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Auditor View ────────────────────────────────────────────────── */
    async loadAuditorView(assessmentId, token) {
      try {
        this.auditorData=await this.api('GET',`/assessments/${assessmentId}/auditor-view?token=${encodeURIComponent(token)}`);
        this._auditorToken=token;
        this._auditorAssessmentId=parseInt(assessmentId);
        this.view='auditorView';
      } catch(e){ this.notify(e.message,'error'); this.view='login'; }
    },

    async addAuditorComment() {
      if (!this._auditorAssessmentId || !this._auditorToken){ this.notify('Session invalid — please reload','error'); return; }
      if (!this.auditorCommentForm.comment_text.trim()){ this.notify('Comment cannot be empty','error'); return; }
      try {
        const id=this._auditorAssessmentId;
        const tok=encodeURIComponent(this._auditorToken);
        await this.api('POST',`/assessments/${id}/comments/external?token=${tok}`,{
          control_id: this.auditorCommentForm.control_id||'general',
          comment_text: this.auditorCommentForm.comment_text,
          is_internal: false,
        });
        this.auditorCommentForm={control_id:'',comment_text:''};
        this.notify('Comment submitted');
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Navigation ──────────────────────────────────────────────────── */
    async nav(v, id) {
      this.view=v;
      if      (v==='dashboard')   await this.loadDashboard();
      else if (v==='assessments') await this.loadAssessments();
      else if (v==='assessment')  {this.sub='overview'; await this.loadAssessment(id);}
      else if (v==='frameworks')  await this.loadFrameworks();
      else if (v==='tools')       await this.loadTools();
      else if (v==='auditlog')    await this.loadAuditLog();
      else if (v==='admin')       await this.loadAdmin();
    },

    async setSubview(s) {
      this.sub=s;
      const id=this.assessment?.id;
      if      (s==='evidence')  await this.loadEvidence(id);
      else if (s==='findings')  await this.loadFindings(id);
      else if (s==='rfis')      await this.loadRFIs(id);
      else if (s==='risk')      await this.loadRiskAcceptances(id);
      else if (s==='shares')    await this.loadAuditorShares(id);
      else if (s==='comments')  await this.loadComments(id);
      else if (s==='log')       await this.loadAssessmentLog(id);
    },

    /* ── Dashboard ───────────────────────────────────────────────────── */
    async loadDashboard() {
      try {
        this.dash=await this.api('GET','/dashboard');
        this.$nextTick(()=>this.renderCharts());
      } catch(e){this.notify(e.message,'error');}
    },

    renderCharts() {
      const fwCtx=document.getElementById('fwChart');
      if (fwCtx&&this.dash?.framework_scores?.length) {
        if (this._fwChart) this._fwChart.destroy();
        const s=this.dash.framework_scores;
        this._fwChart=new Chart(fwCtx,{
          type:'bar',
          data:{labels:s.map(x=>x.framework_name),
            datasets:[{label:'Compliance %',data:s.map(x=>x.score),
              backgroundColor:s.map(x=>x.score>=80?'#16a34a':x.score>=50?'#d97706':'#dc2626'),
              borderRadius:4}]},
          options:{responsive:true,maintainAspectRatio:false,
            plugins:{legend:{display:false}},
            scales:{y:{min:0,max:100,ticks:{callback:v=>v+'%'}}}}
        });
      }
      const findCtx=document.getElementById('findChart');
      if (findCtx&&this.dash?.findings_by_severity&&Object.keys(this.dash.findings_by_severity).length) {
        if (this._findChart) this._findChart.destroy();
        const sv=this.dash.findings_by_severity;
        const col={critical:'#991b1b',high:'#c2410c',medium:'#d97706',low:'#2563eb',informational:'#6b7280'};
        this._findChart=new Chart(findCtx,{
          type:'doughnut',
          data:{labels:Object.keys(sv),
            datasets:[{data:Object.values(sv),backgroundColor:Object.keys(sv).map(k=>col[k]||'#6b7280'),borderWidth:2}]},
          options:{responsive:true,maintainAspectRatio:false,
            plugins:{legend:{position:'bottom',labels:{boxWidth:12,padding:8}}}}
        });
      }
    },

    /* ── Assessments ─────────────────────────────────────────────────── */
    async loadAssessments() {
      try {
        [this.assessments,this.frameworks]=await Promise.all([
          this.api('GET','/assessments/history'),
          this.frameworks.length?Promise.resolve(this.frameworks):this.api('GET','/frameworks'),
        ]);
      } catch(e){this.notify(e.message,'error');}
    },

    async loadAssessment(id) {
      try {
        [this.assessment,this.results,this.assessmentTools,this.userDirectory]=await Promise.all([
          this.api('GET','/assessments/'+id),
          this.api('GET','/assessments/'+id+'/results').catch(()=>({controls:[]})),
          this.api('GET','/assessments/'+id+'/tools').catch(()=>[]),
          this.api('GET','/auth/directory').catch(()=>[]),
        ]);
        this.controls=this.results?.controls||[];
        this.signoffs=await this.api('GET','/assessments/'+id+'/signoffs').catch(()=>[]);
        this.multiFramework=await this.api('GET','/crosswalk/multi-framework?assessment_id='+id).catch(()=>null);
      } catch(e){this.notify(e.message,'error');}
    },

    recurrenceLabel(days) {
      if (!days) return '—';
      if (days % 365 === 0) return (days/365)+(days===365?' year':' years');
      if (days % 91  === 0) return (days/91) +(days===91 ?' quarter':' quarters');
      if (days % 30  === 0) return (days/30) +(days===30 ?' month':' months');
      if (days % 7   === 0) return (days/7)  +(days===7  ?' week':' weeks');
      return days+(days===1?' day':' days');
    },

    async openCreateAssessment() {
      if (!this.frameworks.length) this.frameworks=await this.api('GET','/frameworks').catch(()=>[]);
      this.f={name:'',framework_id:this.frameworks[0]?.id||'',scope_notes:'',is_recurring:false,recurrence_interval:3,recurrence_unit:'months'};
      this.modal='createAssessment';
    },

    async createAssessment() {
      try {
        const mult={days:1,weeks:7,months:30,quarters:91,years:365};
        const recurrenceDays=this.f.is_recurring
          ?Math.round(parseInt(this.f.recurrence_interval||1)*(mult[this.f.recurrence_unit]||1))
          :null;
        const a=await this.api('POST','/assessments',{
          name:this.f.name,framework_id:parseInt(this.f.framework_id),
          scope_notes:this.f.scope_notes||'',is_recurring:this.f.is_recurring,
          recurrence_days:recurrenceDays,
          tool_ids:[],
        });
        this.modal=null; this.notify('Assessment created'); await this.nav('assessment',a.id);
      } catch(e){this.notify(e.message,'error');}
    },

    async cloneAssessment(id) {
      try {
        const a=await this.api('POST','/assessments/'+id+'/clone',{});
        this.notify('Assessment cloned'); await this.nav('assessment',a.id);
      } catch(e){this.notify(e.message,'error');}
    },

    async deleteAssessment(id) {
      try {
        await this.api('DELETE','/assessments/'+id);
        this.notify('Assessment deleted');
        this.assessments=this.assessments.filter(a=>a.id!==id);
        this.view='assessments';
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Lifecycle ───────────────────────────────────────────────────── */
    openLifecycle(action){this.f={action,comments:''}; this.modal='lifecycle';},

    async submitLifecycle() {
      try {
        await this.api('POST','/assessments/'+this.assessment.id+'/lifecycle',
          {action:this.f.action,comments:this.f.comments||''});
        this.modal=null; this.notify('Status updated'); await this.loadAssessment(this.assessment.id);
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Controls ────────────────────────────────────────────────────── */
    get filteredControls() {
      let list=this.controls;
      if (this.ctrlFilter){
        const q=this.ctrlFilter.toLowerCase();
        list=list.filter(c=>c.control_id.toLowerCase().includes(q)||c.title.toLowerCase().includes(q));
      }
      if (this.ctrlStatusFilter) list=list.filter(c=>c.status===this.ctrlStatusFilter);
      return list;
    },

    openControl(ctrl) {
      this.f={
        _ctrl:ctrl, control_id:ctrl.control_id,
        notes:ctrl.notes||'', evidence_url:ctrl.evidence_url||'',
        override_status:ctrl.override_status||'', override_justification:ctrl.override_justification||'',
        assignee:ctrl.assignee||'', due_date:ctrl.due_date?ctrl.due_date.split('T')[0]:'',
        is_applicable:ctrl.is_applicable!==false, exclusion_reason:ctrl.exclusion_reason||'',
        owner:ctrl.owner||'', team:ctrl.team||'', evidence_owner:ctrl.evidence_owner||'',
        review_status:ctrl.review_status||'not_reviewed', review_notes:ctrl.review_notes||'',
      };
      this.modal='control';
    },

    async saveControl() {
      try {
        const id=this.assessment.id; const cid=this.f.control_id;
        await this.api('PATCH',`/assessments/${id}/controls/${cid}/notes`,{
          notes:this.f.notes, evidence_url:this.f.evidence_url||'',
          override_status:this.f.override_status, override_justification:this.f.override_justification||'',
          assignee:this.f.assignee||'',
          due_date:this.f.due_date?new Date(this.f.due_date).toISOString():null,
          is_applicable:this.f.is_applicable, exclusion_reason:this.f.exclusion_reason||'',
        });
        await this.api('PATCH',`/assessments/${id}/controls/${cid}/ownership`,{
          owner:this.f.owner||'',team:this.f.team||'',evidence_owner:this.f.evidence_owner||'',
        });
        await this.api('PATCH',`/assessments/${id}/controls/${cid}/review`,{
          review_status:this.f.review_status||'not_reviewed',
          review_notes:this.f.review_notes||'',
        });
        // Upload attached evidence file if one was selected
        const file=document.getElementById('ctrlEvidenceFile')?.files?.[0];
        if (file) {
          const fd=new FormData();
          fd.append('file',file);
          fd.append('control_id',cid);
          fd.append('description',this.f.evidenceDescription||'');
          if (this.f.evidenceExpires) fd.append('expires_at',new Date(this.f.evidenceExpires).toISOString());
          await this.api('POST','/assessments/'+id+'/evidence',fd,true);
          await this.loadEvidence(id);
        }
        this.modal=null; this.notify('Control saved'); await this.loadAssessment(id);
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Evidence ────────────────────────────────────────────────────── */
    async loadEvidence(id) {
      try{this.evidence=await this.api('GET','/assessments/'+id+'/evidence');}
      catch(e){this.notify(e.message,'error');}
    },

    openEvidenceUpload(){this.f={control_id:'',description:'',expires_at:''}; this.modal='evidence';},

    async uploadEvidence() {
      try {
        const id=this.assessment.id;
        const file=document.getElementById('evidenceFile').files[0];
        if (!file){this.notify('Select a file first','error'); return;}
        const fd=new FormData();
        fd.append('file',file); fd.append('control_id',this.f.control_id);
        fd.append('description',this.f.description||'');
        if (this.f.expires_at) fd.append('expires_at',new Date(this.f.expires_at).toISOString());
        await this.api('POST','/assessments/'+id+'/evidence',fd,true);
        this.modal=null; this.notify('Evidence uploaded'); await this.loadEvidence(id);
      } catch(e){this.notify(e.message,'error');}
    },

    async downloadEvidence(ev) {
      try {
        const r=await fetch(`/assessments/${this.assessment.id}/evidence/${ev.id}/download`,
          {headers:{Authorization:'Bearer '+this.token}});
        if (!r.ok) throw new Error('Download failed');
        const blob=await r.blob();
        const url=URL.createObjectURL(blob);
        const a=document.createElement('a'); a.href=url; a.download=ev.original_filename; a.click();
        setTimeout(()=>URL.revokeObjectURL(url),5000);
      } catch(e){this.notify(e.message,'error');}
    },

    async approveEvidence(fileId, action) {
      if (action==='approve') {
        try {
          await this.api('PATCH',`/assessments/${this.assessment.id}/evidence/${fileId}/approval`,
            {action:'approve',rejection_reason:''});
          this.notify('Evidence approved'); await this.loadEvidence(this.assessment.id);
        } catch(e){this.notify(e.message,'error');}
      } else {
        this.f={_fileId:fileId,rejection_reason:''}; this.modal='evidenceReject';
      }
    },

    async submitRejectEvidence() {
      try {
        await this.api('PATCH',`/assessments/${this.assessment.id}/evidence/${this.f._fileId}/approval`,
          {action:'reject',rejection_reason:this.f.rejection_reason||''});
        this.modal=null; this.notify('Evidence rejected'); await this.loadEvidence(this.assessment.id);
      } catch(e){this.notify(e.message,'error');}
    },

    async deleteEvidence(fileId) {
      try {
        await this.api('DELETE',`/assessments/${this.assessment.id}/evidence/${fileId}`);
        this.notify('Evidence deleted'); await this.loadEvidence(this.assessment.id);
      } catch(e){this.notify(e.message,'error');}
    },

    async downloadFile(url, filename) {
      try {
        const r=await fetch(url,{headers:{Authorization:'Bearer '+this.token}});
        if (!r.ok) throw new Error('Download failed');
        const blob=await r.blob();
        const objUrl=URL.createObjectURL(blob);
        const a=document.createElement('a'); a.href=objUrl; a.download=filename; a.click();
        setTimeout(()=>URL.revokeObjectURL(objUrl),5000);
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Findings ────────────────────────────────────────────────────── */
    async loadFindings(id) {
      try{this.findings=await this.api('GET','/assessments/'+id+'/findings');}
      catch(e){this.notify(e.message,'error');}
    },

    openCreateFinding(){
      this.f={control_id:'',title:'',description:'',severity:'medium',remediation_owner:'',target_date:'',notes:''};
      this.modal='finding';
    },

    openEditFinding(fn){
      this.f={_id:fn.id,title:fn.title,description:fn.description,severity:fn.severity,
        status:fn.status,remediation_owner:fn.remediation_owner,notes:fn.notes,
        target_date:fn.target_date?fn.target_date.split('T')[0]:''};
      this.modal='editFinding';
    },

    async createFinding() {
      try {
        const id=this.assessment.id;
        await this.api('POST','/assessments/'+id+'/findings',{
          control_id:this.f.control_id,title:this.f.title,description:this.f.description||'',
          severity:this.f.severity,remediation_owner:this.f.remediation_owner||'',
          target_date:this.f.target_date?new Date(this.f.target_date).toISOString():null,
          notes:this.f.notes||'',
        });
        this.modal=null; this.notify('Finding created'); await this.loadFindings(id);
      } catch(e){this.notify(e.message,'error');}
    },

    async updateFinding() {
      try {
        const id=this.assessment.id;
        await this.api('PATCH',`/assessments/${id}/findings/${this.f._id}`,{
          title:this.f.title,description:this.f.description,severity:this.f.severity,
          status:this.f.status,remediation_owner:this.f.remediation_owner,notes:this.f.notes,
          target_date:this.f.target_date?new Date(this.f.target_date).toISOString():null,
        });
        this.modal=null; this.notify('Finding updated'); await this.loadFindings(id);
      } catch(e){this.notify(e.message,'error');}
    },

    async deleteFinding(findingId) {
      try {
        await this.api('DELETE',`/assessments/${this.assessment.id}/findings/${findingId}`);
        this.notify('Finding deleted'); await this.loadFindings(this.assessment.id);
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── RFIs ────────────────────────────────────────────────────────── */
    async loadRFIs(id) {
      try{this.rfis=await this.api('GET','/assessments/'+id+'/rfis');}
      catch(e){this.notify(e.message,'error');}
    },

    openCreateRFI(){
      this.f={title:'',description:'',priority:'medium',control_id:'',requested_by:'',assigned_to:'',due_date:''};
      this.modal='rfi';
    },

    async createRFI() {
      try {
        const id=this.assessment.id;
        await this.api('POST','/assessments/'+id+'/rfis',{
          title:this.f.title,description:this.f.description||'',priority:this.f.priority,
          control_id:this.f.control_id||'',requested_by:this.f.requested_by||'',
          assigned_to:this.f.assigned_to||'',
          due_date:this.f.due_date?new Date(this.f.due_date).toISOString():null,
        });
        this.modal=null; this.notify('RFI created'); await this.loadRFIs(id);
      } catch(e){this.notify(e.message,'error');}
    },

    openRFIRespond(rfi){
      this.f={_id:rfi.id,_rfi:rfi,responder_name:this.user?.username||'',response_text:''};
      this.modal='rfiRespond';
    },

    async submitRFIResponse() {
      try {
        const id=this.assessment.id;
        await this.api('POST',`/assessments/${id}/rfis/${this.f._id}/responses`,
          {responder_name:this.f.responder_name,response_text:this.f.response_text});
        await this.api('PATCH',`/assessments/${id}/rfis/${this.f._id}`,{status:'responded'}).catch(()=>{});
        this.modal=null; this.notify('Response submitted'); await this.loadRFIs(id);
      } catch(e){this.notify(e.message,'error');}
    },

    async closeRFI(rfiId) {
      try {
        await this.api('PATCH',`/assessments/${this.assessment.id}/rfis/${rfiId}`,{status:'closed'});
        this.notify('RFI closed'); await this.loadRFIs(this.assessment.id);
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Audit Log ───────────────────────────────────────────────────── */
    async loadAssessmentLog(id) {
      try{this.assessmentLog=await this.api('GET','/audit-log/assessment/'+id);}
      catch(e){this.notify(e.message,'error');}
    },

    async loadAuditLog() {
      try{this.auditLog=await this.api('GET','/audit-log');}
      catch(e){this.notify(e.message,'error');}
    },

    /* ── Frameworks ──────────────────────────────────────────────────── */
    async loadFrameworks() {
      try{this.frameworks=await this.api('GET','/frameworks');}
      catch(e){this.notify(e.message,'error');}
    },

    async toggleFrameworkControls(fw) {
      if (this.frameworkControls[fw.id]){
        const copy={...this.frameworkControls}; delete copy[fw.id]; this.frameworkControls=copy; return;
      }
      try {
        const c=await this.api('GET','/frameworks/'+fw.id+'/controls');
        this.frameworkControls={...this.frameworkControls,[fw.id]:c};
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Tools ───────────────────────────────────────────────────────── */
    async loadTools() {
      try{this.tools=await this.api('GET','/tools');}
      catch(e){this.notify(e.message,'error');}
    },

    openCreateTool(){
      const existingTags=[...new Set(this.tools.flatMap(t=>(t.capabilities||[])))].sort();
      this.f={name:'',category:'',description:'',capabilityTags:[],capNewTag:'',_allTags:existingTags};
      this.modal='tool';
    },

    toggleCapTag(tag){
      const idx=this.f.capabilityTags.indexOf(tag);
      if(idx===-1) this.f.capabilityTags.push(tag);
      else this.f.capabilityTags.splice(idx,1);
    },

    addCustomCapTag(){
      const tag=(this.f.capNewTag||'').trim();
      if(tag && !this.f.capabilityTags.includes(tag)){this.f.capabilityTags.push(tag);}
      this.f.capNewTag='';
    },

    async createTool() {
      try {
        await this.api('POST','/tools',{
          name:this.f.name,category:this.f.category||'',description:this.f.description||'',
          capabilities:this.f.capabilityTags,
        });
        this.modal=null; this.notify('Tool added'); await this.loadTools();
      } catch(e){this.notify(e.message,'error');}
    },

    async deleteTool(id) {
      try{await this.api('DELETE','/tools/'+id); this.notify('Tool deleted'); await this.loadTools();}
      catch(e){this.notify(e.message,'error');}
    },

    openImportTools(){ this.modal='importTools'; },

    async importTools() {
      try {
        const file=document.getElementById('importToolsFile').files[0];
        if (!file){this.notify('Select a file first','error'); return;}
        const fd=new FormData(); fd.append('file',file);
        const r=await this.api('POST','/tools/upload',fd,true);
        this.modal=null; this.notify(`Imported: ${r.added} added, ${r.skipped} skipped`);
        await this.loadTools();
      } catch(e){this.notify(e.message,'error');}
    },

    downloadToolTemplate(){
      this.downloadFile('/tools/template/download','tools_template.json');
    },

    openImportCis(){ this.modal='importCis'; },

    async importCisXlsx() {
      try {
        const file=document.getElementById('importCisFile').files[0];
        if (!file){this.notify('Select a file first','error'); return;}
        const fd=new FormData(); fd.append('file',file);
        const r=await this.api('POST','/import/cis-xlsx',fd,true);
        this.modal=null; this.notify(r.message||'Import complete');
        await this.loadFrameworks();
      } catch(e){this.notify(e.message,'error');}
    },

    openImportNistCsf(){ this.modal='importNistCsf'; },

    async importNistCsfXlsx() {
      try {
        const file=document.getElementById('importNistCsfFile').files[0];
        if (!file){this.notify('Select a file first','error'); return;}
        const fd=new FormData(); fd.append('file',file);
        const r=await this.api('POST','/import/nist-csf-xlsx',fd,true);
        this.modal=null; this.notify(r.message||'Import complete');
        await this.loadFrameworks();
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Admin ───────────────────────────────────────────────────────── */
    async loadAdmin() {
      try {
        [this.users,this.apiTokens]=await Promise.all([
          this.api('GET','/auth/users'), this.api('GET','/api-tokens'),
        ]);
        this.loadBackups();
        this.loadSmtpStatus();
        this.loadOidcConfig();
      } catch(e){this.notify(e.message,'error');}
    },

    openCreateUser(){
      this.f={username:'',password:'',role:'viewer',full_name:'',email:''}; this.modal='createUser';
    },

    openInviteUser(){
      this.f={username:'',role:'viewer',full_name:'',email:''}; this.inviteResult=null; this.modal='inviteUser';
    },

    async sendInvite() {
      try {
        const r=await this.api('POST','/auth/users/invite',{
          username:this.f.username, role:this.f.role,
          full_name:this.f.full_name||'', email:this.f.email||'',
        });
        this.inviteResult=r;
        this.notify('Invite created'+(r.email_sent?' — email sent':'— copy the link'));
        await this.loadAdmin();
      } catch(e){this.notify(e.message,'error');}
    },

    async createUser() {
      try {
        await this.api('POST','/auth/users',this.f);
        this.modal=null; this.notify('User created'); await this.loadAdmin();
      } catch(e){this.notify(e.message,'error');}
    },

    openEditUser(u){
      this.f={_id:u.id,role:u.role,is_active:u.is_active,full_name:u.full_name,email:u.email,password:''};
      this.modal='editUser';
    },

    async updateUser() {
      try {
        const p={role:this.f.role,is_active:this.f.is_active,full_name:this.f.full_name,email:this.f.email};
        if (this.f.password) p.password=this.f.password;
        await this.api('PATCH','/auth/users/'+this.f._id,p);
        this.modal=null; this.notify('User updated'); await this.loadAdmin();
      } catch(e){this.notify(e.message,'error');}
    },

    async deleteUser(id) {
      try{await this.api('DELETE','/auth/users/'+id); this.notify('User deleted'); await this.loadAdmin();}
      catch(e){this.notify(e.message,'error');}
    },

    openCreateToken(){this.f={name:'',expires_at:''}; this.newToken=null; this.modal='createToken';},

    async createApiToken() {
      try {
        const p={name:this.f.name,scopes:[]};
        if (this.f.expires_at) p.expires_at=new Date(this.f.expires_at).toISOString();
        const r=await this.api('POST','/api-tokens',p);
        this.newToken=r.token; this.modal=null;
        this.notify('Token created — copy it now!'); await this.loadAdmin();
      } catch(e){this.notify(e.message,'error');}
    },

    async deleteApiToken(id) {
      try{await this.api('DELETE','/api-tokens/'+id); this.notify('Token revoked'); await this.loadAdmin();}
      catch(e){this.notify(e.message,'error');}
    },

    /* ── Risk Acceptances ────────────────────────────────────────────── */
    async loadRiskAcceptances(id) {
      try{this.riskAcceptances=await this.api('GET','/assessments/'+id+'/risk-acceptances');}
      catch(e){this.notify(e.message,'error');}
    },

    openCreateRiskAcceptance(){
      this.f={control_id:'',justification:'',risk_rating:'medium',residual_risk_notes:'',expires_at:''};
      this.modal='riskAcceptance';
    },

    async createRiskAcceptance() {
      try {
        const id=this.assessment.id;
        await this.api('POST','/assessments/'+id+'/risk-acceptances',{
          control_id:this.f.control_id,
          justification:this.f.justification,
          risk_rating:this.f.risk_rating,
          residual_risk_notes:this.f.residual_risk_notes||'',
          expires_at:this.f.expires_at?new Date(this.f.expires_at).toISOString():null,
        });
        this.modal=null; this.notify('Risk acceptance recorded'); await this.loadRiskAcceptances(id);
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Auditor Shares ──────────────────────────────────────────────── */
    async loadAuditorShares(id) {
      try{this.auditorShares=await this.api('GET','/assessments/'+id+'/auditor-shares');}
      catch(e){this.notify(e.message,'error');}
    },

    openCreateShare(){
      this.f={auditor_name:'',auditor_email:'',expires_at:''}; this.newShareToken=null; this.modal='createShare';
    },

    async createAuditorShare() {
      try {
        const id=this.assessment.id;
        const p={auditor_name:this.f.auditor_name,auditor_email:this.f.auditor_email||''};
        if (this.f.expires_at) p.expires_at=new Date(this.f.expires_at).toISOString();
        const r=await this.api('POST','/assessments/'+id+'/auditor-shares',p);
        this.newShareToken=r.token; this.modal=null;
        this.notify('Share link created — copy the token now!');
        await this.loadAuditorShares(id);
      } catch(e){this.notify(e.message,'error');}
    },

    async revokeShare(shareId) {
      try {
        await this.api('DELETE',`/assessments/${this.assessment.id}/auditor-shares/${shareId}`);
        this.notify('Share revoked'); await this.loadAuditorShares(this.assessment.id);
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Comments ────────────────────────────────────────────────────── */
    async loadComments(id) {
      try{this.comments=await this.api('GET','/assessments/'+id+'/comments');}
      catch(e){this.notify(e.message,'error');}
    },

    openCreateComment(){
      this.f={control_id:'',comment_text:'',is_internal:false}; this.modal='comment';
    },

    async submitComment() {
      try {
        const id=this.assessment.id;
        await this.api('POST','/assessments/'+id+'/comments',{
          control_id: this.f.control_id||'general',
          comment_text: this.f.comment_text,
          is_internal: this.f.is_internal,
        });
        this.modal=null; this.f={}; this.notify('Comment posted'); await this.loadComments(id);
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Tool Management ─────────────────────────────────────────────── */
    async openManageTools() {
      if (!this.tools.length) this.tools=await this.api('GET','/tools').catch(()=>[]);
      this.f={toolIds:this.assessmentTools.map(t=>t.id)};
      this.modal='manageTools';
    },

    async saveAssessmentTools() {
      try {
        const id=this.assessment.id;
        await this.api('PATCH','/assessments/'+id+'/tools',{tool_ids:this.f.toolIds.map(id=>parseInt(id))});
        this.modal=null; this.notify('Tools updated');
        await this.loadAssessment(id);
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Crosswalk ───────────────────────────────────────────────────── */
    async loadCrosswalk() {
      if (!this.crosswalkSrc || !this.crosswalkTgt) return;
      try {
        this.crosswalkData=await this.api('GET',
          `/crosswalk?source_framework_id=${this.crosswalkSrc}&target_framework_id=${this.crosswalkTgt}`);
      } catch(e){this.notify(e.message,'error');}
    },

    /* ── Confirm dialog ──────────────────────────────────────────────── */
    confirmDelete(msg,cb){this.confirmMsg=msg; this.confirmCb=cb; this.modal='confirm';},
    doConfirm(){if(this.confirmCb)this.confirmCb(); this.modal=null; this.confirmCb=null;},

  };
}
