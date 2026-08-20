/* ============================================
   LAWoud — Script
   AI Chatbot for Constitutional Awareness & Legal Aid
   ============================================ */

(function () {
  'use strict';

  // ======================== DOM REFERENCES ========================
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const DOM = {
    app: $('#app'),
    sidebar: $('#sidebar'),
    sidebarOverlay: $('#sidebarOverlay'),
    sidebarCollapseBtn: $('#sidebarCollapseBtn'),
    mobileMenuBtn: $('#mobileMenuBtn'),
    newChatSidebar: $('#newChatSidebar'),
    newChatHeader: $('#newChatHeader'),
    navItems: $$('.nav-item'),
    recentChats: $('#recentChats'),

    accountBtn: $('#accountBtn'),
    accountDropdown: $('#accountDropdown'),

    // theme toggle removed - dark mode only

    shareBtn: $('#shareBtn'),
    saveChatBtn: $('#saveChatBtn'),

    chatArea: $('#chatArea'),
    welcomeState: $('#welcomeState'),
    chatMessages: $('#chatMessages'),
    chatInput: $('#chatInput'),
    sendBtn: $('#sendBtn'),
    attachBtn: $('#attachBtn'),
    micBtn: $('#micBtn'),
    fileInput: $('#fileInput'),
    attachedFile: $('#attachedFile'),
    attachedFileName: $('#attachedFileName'),
    removeFileBtn: $('#removeFileBtn'),

    headerTitle: $('#headerTitle'),
    headerSubtitle: $('#headerSubtitle'),

    modalOverlay: $('#modalOverlay'),
    shareModal: $('#shareModal'),
    shareModalClose: $('#shareModalClose'),
    shareLinkInput: $('#shareLinkInput'),
    shareCopyBtn: $('#shareCopyBtn'),

    legalHelpModal: $('#legalHelpModal'),
    legalHelpModalClose: $('#legalHelpModalClose'),
    legalHelpCtaBtn: $('#legalHelpCtaBtn'),

    chatHistoryModal: $('#chatHistoryModal'),
    chatHistoryModalClose: $('#chatHistoryModalClose'),
    historyList: $('#historyList'),

    toast: $('#toast'),
    toastMessage: $('#toastMessage'),
  };

  // ======================== STATE ========================
  const state = {
    currentView: 'welcome', // 'welcome' | 'chat'
    theme: 'dark',
    sidebarOpen: false,
    activeDropdown: null,
    isRecording: false,
    recognition: null,
    attachedFileName: null,
    conversations: {
      1: {
        title: 'What are my rights if police...',
        time: '11:30 AM',
        messages: [
          { type: 'user', text: 'What are my rights if the police search my house without a warrant?', time: '11:28 AM' },
          { type: 'ai', text: 'I understand your concern.\n\nGenerally, police officers are required to obtain a warrant from a magistrate before searching a residence, except in certain urgent circumstances defined by law.\n\nThere may be legal protections relevant to your situation.\n\nLet\'s look at your rights and the relevant law.' }
        ]
      },
      2: {
        title: 'Landlord not returning deposit',
        time: 'Yesterday',
        messages: [
          { type: 'user', text: 'My landlord is refusing to return my security deposit after I vacated the flat. What can I do?', time: '3:45 PM' },
          { type: 'ai', text: 'I understand what happened.\n\nYou vacated your rented flat and your landlord is not returning your security deposit.\n\nThere may be legal remedies available to you under tenancy and consumer protection laws.\n\nLet\'s look at your rights, the relevant law, and what you can do next.' }
        ]
      },
      3: {
        title: 'Police stopped me and took...',
        time: '2 days ago',
        messages: [
          { type: 'user', text: 'Police stopped me and took my phone.\nThey didn\'t tell me why. Is that allowed?', time: '10:42 AM' },
          { type: 'ai', text: 'I understand what happened.\n\nYou were stopped by police and your phone was taken without an explanation.\n\nThere may be legal protections relevant to your situation.\n\nLet\'s look at your rights, the relevant law, and what you can do next.' }
        ]
      },
      4: {
        title: 'How to file a complaint online?',
        time: '3 days ago',
        messages: [
          { type: 'user', text: 'How can I file a complaint online against a company that refused to give me a refund?', time: '2:15 PM' },
          { type: 'ai', text: 'I can help with that.\n\nThere are several online platforms where consumers can file complaints against businesses.\n\nLet me guide you through the options available and the steps involved.' }
        ]
      },
      5: {
        title: 'Inheritance laws in India',
        time: '4 days ago',
        messages: [
          { type: 'user', text: 'What are the inheritance laws in India? My father passed away without a will.', time: '9:30 AM' },
          { type: 'ai', text: 'I\'m sorry for your loss.\n\nWhen a person passes away without a will (intestate), the distribution of property is generally governed by personal laws applicable to the family.\n\nLet me explain the relevant concepts and what you may need to consider.' }
        ]
      }
    },
    currentChatId: null,
    currentMessages: [],
  };

  // ======================== LEGAL CONTENT DATA ========================
  const LEGAL_CONTENT = {
    rights: {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
      title: 'Your Rights',
      content: `<p>Based on what you described, some legal protections may be relevant:</p>
        <div class="simple-explain">
          <div class="label">Article 21 — Right to Life & Personal Liberty</div>
          <p>The government cannot interfere with your personal liberty arbitrarily. This includes your right to your personal belongings.</p>
        </div>
        <div class="simple-explain">
          <div class="label">Article 22 — Protection Against Arbitrary Arrest</div>
          <p>If you are detained, you generally have the right to be informed of the reason. This principle can extend to the seizure of personal property.</p>
        </div>
        <p>In simple words: You may have the right to know why your property was taken and to be treated according to lawful procedure.</p>`,
      actions: ['Explain this simply', 'Show source']
    },
    law: {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
      title: 'Relevant Law',
      content: `<p><strong>Relevant Provision</strong></p>
        <p>Article 21 of the Constitution of India</p>
        <div class="legal-quote">"No person shall be deprived of his life or personal liberty except according to procedure established by law."</div>
        <div class="simple-explain">
          <div class="label">In Simple English</div>
          <p>The state cannot take away your freedom or your belongings without following proper legal procedures. Any such action must be backed by a specific law and carried out through a fair process.</p>
        </div>
        <p><strong>Why it may apply to your situation:</strong></p>
        <p>Based on what you described, your phone was taken without an explanation. This may raise questions about whether proper procedure was followed.</p>`,
      actions: ['View source', 'Explain simply']
    },
    todo: {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
      title: 'What You Can Do',
      content: `<p>Here are some steps you may consider:</p>
        <ol>
          <li>Keep a clear record of what happened — note the date, time, location, and any officers involved.</li>
          <li>Politely ask for the reason your phone was taken and request written acknowledgment if possible.</li>
          <li>Note any witnesses or nearby details that may be relevant.</li>
          <li>Preserve any related messages, photos, or documents you may have.</li>
          <li>Consider seeking legal assistance if you believe proper procedure was not followed.</li>
        </ol>`,
      actions: ['Draft a Message', 'Get legal help']
    },
    why: {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
      title: 'Why This Applies',
      content: `<p>Here's the connection between your situation and the legal concepts shown:</p>
        <div class="simple-explain">
          <div class="label">Your Statement</div>
          <p>"Police stopped me and took my phone. They didn't tell me why."</p>
        </div>
        <p>↓</p>
        <div class="simple-explain">
          <div class="label">Legal Concept</div>
          <p>Right to personal liberty and lawful procedure (Article 21)</p>
        </div>
        <p>↓</p>
        <div class="simple-explain">
          <div class="label">Why It May Be Relevant</div>
          <p>You said your phone was taken without an explanation. That's why information about lawful procedure and personal liberty was shown — these concepts may be relevant when personal property is taken without stated reasons.</p>
        </div>
        <p>This is meant to help you understand the reasoning. It is not a legal conclusion.</p>`,
      actions: ['Ask a follow-up']
    },
    situation: {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
      title: 'Situation Check',
      content: `<p>Based on what you described, here is a general assessment:</p>
        <div class="situation-level moderate">
          <span class="situation-dot"></span>
          <span class="situation-label">Moderate Attention Recommended</span>
        </div>
        <p><strong>Why:</strong></p>
        <p>Having personal property taken without explanation may involve questions about lawful procedure. While it may not require immediate emergency action, it is generally advisable to document what happened and seek clarification.</p>
        <p style="margin-top:12px;font-size:0.8rem;color:var(--text-dim);">Note: This is not a legal verdict. The actual implications can depend on the specific circumstances. Consider consulting a legal professional for a thorough assessment.</p>`,
      actions: ['Get legal help', 'Ask a follow-up']
    },
    help: {
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>`,
      title: 'Get Legal Help',
      openModal: true
    }
  };

  // Demo AI responses for follow-up
  const DEMO_RESPONSES = [
    'Based on what you\'ve shared, there are a few additional points to consider.\n\nThe right to seek legal remedy is generally available to anyone who believes their rights may have been affected.\n\nYou may want to document the details of the incident while they are fresh in your memory.\n\nWould you like me to explain any specific aspect in more detail?',
    'That\'s a good question.\n\nGenerally, the applicable laws may vary depending on the specific circumstances and jurisdiction.\n\nI can provide more information about the relevant legal provisions if you share additional details about your situation.\n\nRemember, this is general legal information, not professional legal advice.',
    'I understand your concern.\n\nThere are several factors that may be relevant in this situation.\n\nThe key principles typically involve fundamental rights, procedural safeguards, and available remedies.\n\nWould you like me to elaborate on any of these aspects?',
    'Thank you for providing that context.\n\nBased on the additional information, there may be specific provisions that are particularly relevant.\n\nIt\'s generally advisable to keep written records of all interactions and any correspondence related to the matter.\n\nShall I explain the steps you might consider taking?',
    'I can help clarify that.\n\nIn Indian law, there are multiple layers of protection — constitutional rights, statutory provisions, and common law principles.\n\nThe applicability can depend on the specific facts of your case.\n\nWould you like me to break down any particular aspect further?'
  ];

  let demoResponseIndex = 0;

  // ======================== UTILITIES ========================
  function getCurrentTime() {
    const now = new Date();
    let h = now.getHours();
    const m = now.getMinutes().toString().padStart(2, '0');
    const ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    return `${h}:${m} ${ampm}`;
  }

  function showToast(message) {
    DOM.toastMessage.textContent = message;
    DOM.toast.classList.add('show');
    setTimeout(() => DOM.toast.classList.remove('show'), 2500);
  }

  function scrollToBottom() {
    if (DOM.chatMessages) {
      setTimeout(() => {
        DOM.chatMessages.scrollTop = DOM.chatMessages.scrollHeight;
      }, 50);
    }
  }

  function loadLocalConversations() {
    const saved = localStorage.getItem('lawoud-conversations');
    if (saved) {
      try {
        state.conversations = JSON.parse(saved);
      } catch (e) {
        console.error('Failed to parse saved conversations', e);
      }
    } else {
      saveLocalConversations();
    }
  }

  // Save changes to localStorage database
  function saveLocalConversations() {
    localStorage.setItem('lawoud-conversations', JSON.stringify(state.conversations));
  }

  // Dynamically render list items in DOM from active state
  function renderRecentChats() {
    if (!DOM.recentChats) return;
    DOM.recentChats.innerHTML = '';
    
    const entries = Object.entries(state.conversations).sort((a, b) => b[0] - a[0]);
    
    entries.forEach(([id, conv]) => {
      const item = document.createElement('div');
      item.className = 'recent-chat-item';
      if (state.currentChatId === parseInt(id)) {
        item.classList.add('active');
      }
      item.role = 'listitem';
      item.tabIndex = 0;
      item.dataset.chatId = id;
      item.innerHTML = `
        <span class="chat-title">${conv.title}</span>
        <span class="chat-time">${conv.time}</span>
      `;
      
      item.addEventListener('click', () => {
        loadChat(parseInt(id));
      });
      item.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          loadChat(parseInt(id));
        }
      });
      
      DOM.recentChats.appendChild(item);
    });
  }

  function toggleSidebarDesktop() {
    DOM.sidebar.classList.toggle('collapsed');
    DOM.mobileMenuBtn.classList.toggle('show-desktop', DOM.sidebar.classList.contains('collapsed'));
  }

  // ======================== THEME ========================
  function initTheme() {
    // Dark mode only — always apply dark theme
    document.documentElement.setAttribute('data-theme', 'dark');
    state.theme = 'dark';
  }

  // ======================== SIDEBAR ========================
  function openSidebar() {
    state.sidebarOpen = true;
    DOM.sidebar.classList.add('open');
    DOM.sidebarOverlay.classList.add('show');
    document.body.style.overflow = 'hidden';
  }

  function closeSidebar() {
    state.sidebarOpen = false;
    DOM.sidebar.classList.remove('open');
    DOM.sidebarOverlay.classList.remove('show');
    document.body.style.overflow = '';
  }

  function handleNavClick(navItem) {
    DOM.navItems.forEach(n => n.classList.remove('active'));
    navItem.classList.add('active');

    const nav = navItem.dataset.nav;
    closeSidebar();

    switch (nav) {
      case 'chat':
        // Already in chat view
        break;
      case 'history':
        openChatHistory();
        break;
      case 'rights':
        startDemoChat('What are my fundamental rights as an Indian citizen?',
          'Great question!\n\nAs an Indian citizen, you have several fundamental rights guaranteed by the Constitution:\n\nThese include the right to equality, right to freedom, right against exploitation, right to freedom of religion, cultural and educational rights, and the right to constitutional remedies.\n\nLet me explain each one and how they may apply in everyday situations.');
        break;
      case 'constitution':
        startDemoChat('Tell me about the Indian Constitution.',
          'The Constitution of India is the supreme law of the country.\n\nIt was adopted on 26 November 1949 and came into effect on 26 January 1950.\n\nIt establishes the framework of government, defines fundamental rights, directive principles, and the duties of citizens.\n\nWould you like to know about a specific part or article?');
        break;
      case 'findlaw':
        startDemoChat('I need to find a law related to consumer protection.',
          'I can help you find relevant laws.\n\nThe Consumer Protection Act, 2019 is the primary legislation that safeguards consumer rights in India.\n\nIt covers various aspects including product liability, unfair trade practices, and provides mechanisms for consumer dispute resolution.\n\nCan you tell me more about your specific situation?');
        break;
      case 'legalaid':
        openLegalHelp();
        break;
      case 'docexplainer':
        startDemoChat('I have a legal document I need help understanding.',
          'I can help you understand legal documents.\n\nYou can share the text or attach a document, and I\'ll break down the legal language into simple terms.\n\nPlease share the document or describe what it contains, and I\'ll explain it step by step.');
        break;
    }
  }

  // ======================== ACCOUNT DROPDOWN ========================
  function openAccountMenu() {
    DOM.accountDropdown.classList.add('show');
    DOM.accountBtn.classList.add('open');
    DOM.accountBtn.setAttribute('aria-expanded', 'true');
  }

  function closeAccountMenu() {
    DOM.accountDropdown.classList.remove('show');
    DOM.accountBtn.classList.remove('open');
    DOM.accountBtn.setAttribute('aria-expanded', 'false');
  }

  function toggleAccountMenu() {
    if (DOM.accountDropdown.classList.contains('show')) {
      closeAccountMenu();
    } else {
      openAccountMenu();
    }
  }

  // ======================== MODALS ========================
  function openModal(modal) {
    DOM.modalOverlay.classList.add('show');
    modal.classList.add('show');
  }

  function closeAllModals() {
    DOM.modalOverlay.classList.remove('show');
    $$('.modal.show').forEach(m => m.classList.remove('show'));
  }

  function openShareModal() {
    openModal(DOM.shareModal);
  }

  function openLegalHelp() {
    openModal(DOM.legalHelpModal);
  }

  function openChatHistory() {
    // Populate history
    DOM.historyList.innerHTML = '';
    Object.entries(state.conversations).forEach(([id, conv]) => {
      const item = document.createElement('div');
      item.className = 'history-item';
      item.tabIndex = 0;
      item.setAttribute('role', 'button');
      item.setAttribute('aria-label', conv.title);
      item.innerHTML = `
        <span class="h-title">${conv.title}</span>
        <span class="h-time">${conv.time}</span>
      `;
      item.addEventListener('click', () => {
        closeAllModals();
        loadChat(parseInt(id));
      });
      item.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          closeAllModals();
          loadChat(parseInt(id));
        }
      });
      DOM.historyList.appendChild(item);
    });
    openModal(DOM.chatHistoryModal);
  }

  // ======================== CHAT MANAGEMENT ========================
  function switchToChat() {
    state.currentView = 'chat';
    DOM.welcomeState.classList.add('hidden');
    DOM.chatMessages.classList.remove('hidden');
    DOM.newChatHeader.classList.remove('hidden');
    DOM.chatInput.placeholder = 'Ask a follow-up question...';
    DOM.headerTitle.textContent = 'LAWoud';
    DOM.headerSubtitle.textContent = 'Your Constitutional & Legal Awareness Assistant';
  }

  function switchToWelcome() {
    state.currentView = 'welcome';
    state.currentChatId = null;
    state.currentMessages = [];
    DOM.welcomeState.classList.remove('hidden');
    DOM.chatMessages.classList.add('hidden');
    DOM.chatMessages.innerHTML = '';
    DOM.newChatHeader.classList.add('hidden');
    DOM.chatInput.placeholder = 'Type your legal question here...';
    DOM.chatInput.value = '';
    DOM.chatInput.style.height = 'auto';
        DOM.headerTitle.innerHTML = '<span class="law">LAW</span><span class="oud" style="color:var(--gold);">oud</span>';
    DOM.headerSubtitle.textContent = 'Your Constitutional & Legal Awareness Assistant';
    removeAttachment();
  }

  function newChat() {
    switchToWelcome();
    DOM.navItems.forEach(n => n.classList.remove('active'));
    DOM.navItems[0].classList.add('active');
    renderRecentChats();
  }

  function loadChat(chatId) {
    const conv = state.conversations[chatId];
    if (!conv) return;

    state.currentChatId = chatId;
    state.currentMessages = [...conv.messages];

    switchToChat();
    DOM.chatMessages.innerHTML = '';

    conv.messages.forEach((msg, idx) => {
      addMessageToDOM(msg.type, msg.text, msg.time, idx === conv.messages.length - 1 && msg.type === 'ai');
    });

    renderRecentChats();
    scrollToBottom();
    closeSidebar();
  }

  function startDemoChat(userText, aiReply) {
    const newId = Date.now();
    state.conversations[newId] = {
      title: userText.substring(0, 30) + (userText.length > 30 ? '...' : ''),
      time: getCurrentTime(),
      messages: []
    };
    state.currentChatId = newId;
    state.currentMessages = state.conversations[newId].messages;

    switchToChat();
    DOM.chatMessages.innerHTML = '';
    renderRecentChats();

    addMessage('user', userText);
    setTimeout(() => {
      showTypingIndicator();
      setTimeout(() => {
        removeTypingIndicator();
        addMessage('ai', aiReply);
      }, 1200);
    }, 300);
  }

  // ======================== MESSAGES ========================
  function addMessage(type, text) {
    const time = getCurrentTime();
    const msg = { type, text, time };
    state.currentMessages.push(msg);

    if (state.currentChatId && state.conversations[state.currentChatId]) {
      state.conversations[state.currentChatId].messages = state.currentMessages;
      saveLocalConversations();
    }

    const isLast = type === 'ai';
    addMessageToDOM(type, text, time, isLast);
    scrollToBottom();
  }

  function addMessageToDOM(type, text, time, showCTAs) {
    const wrapper = document.createElement('div');
    wrapper.className = `message ${type}`;

    const avatarSVG = type === 'ai'
      ? `<svg viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
           <path d="M18 4v24M11 10h14M7 10l4 10h0a5 5 0 0010 0h0l4-10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" fill="none"/>
           <path d="M7 20c0 2.8 2.2 3.5 4 3.5s4-.7 4-3.5" stroke="currentColor" stroke-width="1.5" fill="none"/>
           <path d="M21 20c0 2.8 2.2 3.5 4 3.5s4-.7 4-3.5" stroke="currentColor" stroke-width="1.5" fill="none"/>
           <path d="M13 28h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
         </svg>`
      : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
           <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
         </svg>`;

    const paragraphs = text.split('\n').filter(p => p.trim()).map(p => `<p>${p}</p>`).join('');

    let metaHTML = '';
    if (type === 'user') {
      metaHTML = `
        <div class="message-meta">
          <span class="message-time">${time || getCurrentTime()}</span>
          <span class="message-status">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="1 12 5 16 10 10"/>
              <polyline points="7 12 11 16 20 6"/>
            </svg>
          </span>
        </div>`;
    }

    let actionsHTML = '';
    if (type === 'ai') {
      actionsHTML = `
        <div class="message-actions">
          <button class="msg-action-btn" aria-label="Like" title="Like" data-action="like">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
            </svg>
          </button>
          <button class="msg-action-btn" aria-label="Dislike" title="Dislike" data-action="dislike">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>
            </svg>
          </button>
          <button class="msg-action-btn" aria-label="Copy" title="Copy response" data-action="copy">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
          </button>
        </div>`;
    }

    wrapper.innerHTML = `
      <div class="message-avatar" aria-hidden="true">${avatarSVG}</div>
      <div class="message-content">
        <div class="message-bubble">${paragraphs}</div>
        ${metaHTML}
        ${actionsHTML}
      </div>
    `;

    DOM.chatMessages.appendChild(wrapper);

    // Add message action listeners
    wrapper.querySelectorAll('.msg-action-btn').forEach(btn => {
      btn.addEventListener('click', () => handleMessageAction(btn, text));
    });

    // Add CTAs after AI response
    if (showCTAs && type === 'ai') {
      setTimeout(() => {
        addLegalCTAs();
        scrollToBottom();
      }, 200);
    }
  }

  function handleMessageAction(btn, text) {
    const action = btn.dataset.action;
    switch (action) {
      case 'like':
        btn.classList.toggle('liked');
        if (btn.classList.contains('liked')) showToast('Response liked');
        break;
      case 'dislike':
        btn.classList.toggle('liked');
        if (btn.classList.contains('liked')) showToast('Feedback submitted');
        break;
      case 'copy':
        navigator.clipboard.writeText(text).then(() => showToast('Copied to clipboard'));
        break;
    }
  }

  // ======================== LEGAL CTA CARDS ========================
  function addLegalCTAs() {
    const ctaData = [
      { key: 'rights', label: 'Your Rights', icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>` },
      { key: 'law', label: 'Relevant Law', icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>` },
      { key: 'todo', label: 'What You Can Do', icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 12l2 2 4-4"/></svg>` },
      { key: 'why', label: 'Why This Applies', icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>` },
      { key: 'situation', label: 'Situation Check', icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>` },
      { key: 'help', label: 'Get Legal Help', icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>` },
    ];

    const container = document.createElement('div');
    container.className = 'legal-ctas';

    ctaData.forEach(cta => {
      const btn = document.createElement('button');
      btn.className = 'legal-cta';
      btn.setAttribute('aria-label', cta.label);
      btn.innerHTML = `
        <div class="legal-cta-icon">${cta.icon}</div>
        <span class="legal-cta-title">${cta.label}</span>
      `;
      btn.addEventListener('click', () => showLegalSection(cta.key));
      container.appendChild(btn);
    });

    DOM.chatMessages.appendChild(container);
  }

  // ======================== LEGAL SECTIONS ========================
  function showLegalSection(type) {
    const data = LEGAL_CONTENT[type];
    if (!data) return;

    // If it's help, open modal instead
    if (data.openModal) {
      openLegalHelp();
      return;
    }

    const section = document.createElement('div');
    section.className = 'legal-section';

    let actionsHTML = '';
    if (data.actions && data.actions.length > 0) {
      actionsHTML = `<div class="legal-section-actions">
        ${data.actions.map(a => {
          if (a === 'Draft a Message') {
            return `<button class="legal-action-btn" data-section-action="draft">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              ${a}
            </button>`;
          }
          if (a === 'Get legal help') {
            return `<button class="legal-action-btn" data-section-action="help">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
              ${a}
            </button>`;
          }
          if (a === 'Ask a follow-up') {
            return `<button class="legal-action-btn" data-section-action="followup">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              ${a}
            </button>`;
          }
          return `<button class="legal-action-btn" data-section-action="info">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            ${a}
          </button>`;
        }).join('')}
      </div>`;
    }

    section.innerHTML = `
      <div class="legal-section-card">
        <div class="legal-section-header">
          ${data.icon}
          <h3>${data.title}</h3>
        </div>
        <div class="legal-section-body">
          ${data.content}
        </div>
        ${actionsHTML}
      </div>
    `;

    // Add action listeners
    DOM.chatMessages.appendChild(section);

    section.querySelectorAll('.legal-action-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.sectionAction;
        switch (action) {
          case 'draft':
            addMessage('ai', 'Here\'s a draft message you could use:\n\n"Dear Sir/Madam,\n\nI am writing to inquire about an incident that occurred on [date] at [location]. During the incident, my mobile phone was taken by officers without a stated reason.\n\nI respectfully request clarification regarding the basis for this action and information about when my property may be returned.\n\nI have noted the relevant details for my records.\n\nThank you for your time.\n\nSincerely,\n[Your Name]"\n\nYou can modify this to match your specific situation.');
            break;
          case 'help':
            openLegalHelp();
            break;
          case 'followup':
            DOM.chatInput.focus();
            break;
          default:
            showToast('Information displayed in the section above');
        }
      });
    });

    scrollToBottom();
  }

  // ======================== SEND MESSAGE ========================
  function sendMessage() {
    const text = DOM.chatInput.value.trim();
    if (!text) return;

    if (state.currentView !== 'chat') {
      switchToChat();
    }

    DOM.chatInput.value = '';
    DOM.chatInput.style.height = 'auto';
    removeAttachment();

    if (state.currentChatId === null) {
      const newId = Date.now();
      state.conversations[newId] = {
        title: text.substring(0, 30) + (text.length > 30 ? '...' : ''),
        time: getCurrentTime(),
        messages: []
      };
      state.currentChatId = newId;
      state.currentMessages = state.conversations[newId].messages;
      renderRecentChats();
    }

    addMessage('user', text);

    // Show typing then AI response
    setTimeout(() => {
      showTypingIndicator();
      const delay = 800 + Math.random() * 1200;
      setTimeout(() => {
        removeTypingIndicator();
        const response = DEMO_RESPONSES[demoResponseIndex % DEMO_RESPONSES.length];
        demoResponseIndex++;
        addMessage('ai', response);
      }, delay);
    }, 300);
  }

  // ======================== TYPING INDICATOR ========================
  function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.id = 'typingIndicator';
    indicator.innerHTML = `
      <div class="message-avatar" aria-hidden="true" style="background:linear-gradient(135deg,rgba(216,155,60,0.15),rgba(216,155,60,0.05));border:1px solid var(--border-gold);color:var(--gold);">
        <svg viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" style="width:18px;height:18px;">
          <path d="M18 4v24M11 10h14M7 10l4 10h0a5 5 0 0010 0h0l4-10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" fill="none"/>
          <path d="M7 20c0 2.8 2.2 3.5 4 3.5s4-.7 4-3.5" stroke="currentColor" stroke-width="1.5" fill="none"/>
          <path d="M21 20c0 2.8 2.2 3.5 4 3.5s4-.7 4-3.5" stroke="currentColor" stroke-width="1.5" fill="none"/>
          <path d="M13 28h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </div>
      <div class="typing-dots" aria-label="LAWoud is typing">
        <span></span><span></span><span></span>
      </div>
    `;
    DOM.chatMessages.appendChild(indicator);
    scrollToBottom();
  }

  function removeTypingIndicator() {
    const indicator = $('#typingIndicator');
    if (indicator) indicator.remove();
  }

  // ======================== FILE ATTACHMENT ========================
  function handleFileSelect(e) {
    const file = e.target.files[0];
    if (file) {
      state.attachedFileName = file.name;
      DOM.attachedFileName.textContent = file.name;
      DOM.attachedFile.classList.add('show');
    }
  }

  function removeAttachment() {
    state.attachedFileName = null;
    DOM.attachedFile.classList.remove('show');
    DOM.fileInput.value = '';
  }

  // ======================== VOICE INPUT ========================
  function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      state.recognition = new SpeechRecognition();
      state.recognition.continuous = false;
      state.recognition.interimResults = false;
      state.recognition.lang = 'en-IN';

      state.recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        DOM.chatInput.value = transcript;
        stopRecording();
      };

      state.recognition.onerror = () => {
        stopRecording();
        showToast('Voice input unavailable. Please type your question.');
      };

      state.recognition.onend = () => {
        stopRecording();
      };
    }
  }

  function toggleRecording() {
    if (!state.recognition) {
      showToast('Voice input is not supported in this browser.');
      return;
    }

    if (state.isRecording) {
      state.recognition.stop();
      stopRecording();
    } else {
      state.recognition.start();
      startRecording();
    }
  }

  function startRecording() {
    state.isRecording = true;
    DOM.micBtn.classList.add('recording-indicator');
    DOM.micBtn.title = 'Stop recording';
  }

  function stopRecording() {
    state.isRecording = false;
    DOM.micBtn.classList.remove('recording-indicator');
    DOM.micBtn.title = 'Use voice input';
  }

  // ======================== EVENT LISTENERS ========================
  function bindEvents() {
    // Sidebar
    DOM.mobileMenuBtn.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        openSidebar();
      } else {
        toggleSidebarDesktop();
      }
    });
    DOM.sidebarOverlay.addEventListener('click', closeSidebar);
    DOM.sidebarCollapseBtn.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        closeSidebar();
      } else {
        toggleSidebarDesktop();
      }
    });

    // Nav items
    DOM.navItems.forEach(item => {
      item.addEventListener('click', () => handleNavClick(item));
    });

    // New Chat
    DOM.newChatSidebar.addEventListener('click', newChat);
    DOM.newChatHeader.addEventListener('click', newChat);

    // Textarea Auto-Resize Focus and Input
    DOM.chatInput.addEventListener('input', () => {
      DOM.chatInput.style.height = 'auto';
      DOM.chatInput.style.height = DOM.chatInput.scrollHeight + 'px';
    });

    // Account
    DOM.accountBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleAccountMenu();
    });

    $$('.dropdown-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        const action = item.dataset.action;
        closeAccountMenu();
        switch (action) {
          case 'profile':
            showToast('Profile settings coming soon');
            break;
          case 'settings':
            showToast('Settings coming soon');
            break;
          case 'logout':
            showToast('Logged out');
            break;
        }
      });
    });

    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
      if (!DOM.accountBtn.contains(e.target) && !DOM.accountDropdown.contains(e.target)) {
        closeAccountMenu();
      }
    });

    // Share
    DOM.shareBtn.addEventListener('click', openShareModal);
    DOM.shareModalClose.addEventListener('click', closeAllModals);
    DOM.shareCopyBtn.addEventListener('click', () => {
      DOM.shareLinkInput.select();
      navigator.clipboard.writeText(DOM.shareLinkInput.value).then(() => {
        showToast('Link copied to clipboard');
        closeAllModals();
      });
    });

    // Save Chat
    DOM.saveChatBtn.addEventListener('click', () => {
      showToast('Chat saved successfully');
    });

    // Legal Help
    DOM.legalHelpCtaBtn.addEventListener('click', openLegalHelp);
    DOM.legalHelpModalClose.addEventListener('click', closeAllModals);

    // Chat History Modal
    DOM.chatHistoryModalClose.addEventListener('click', closeAllModals);

    // Modal overlay close
    DOM.modalOverlay.addEventListener('click', closeAllModals);

    // Chat Input
    DOM.chatInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    DOM.sendBtn.addEventListener('click', sendMessage);

    // File attachment
    DOM.attachBtn.addEventListener('click', () => DOM.fileInput.click());
    DOM.fileInput.addEventListener('change', handleFileSelect);
    DOM.removeFileBtn.addEventListener('click', removeAttachment);

    // Mic
    DOM.micBtn.addEventListener('click', toggleRecording);

    // Keyboard: Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeAllModals();
        closeAccountMenu();
        closeSidebar();
      }
    });

    // Window resize handler
    window.addEventListener('resize', () => {
      if (window.innerWidth > 768) {
        closeSidebar();
      }
    });
  }

  // ======================== INIT ========================
  function init() {
    loadLocalConversations();
    initTheme();
    initSpeechRecognition();
    renderRecentChats();
    bindEvents();
  }

  // Start the app
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
