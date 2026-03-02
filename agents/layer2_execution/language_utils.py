"""
agents/layer2_execution/language_utils.py
──────────────────────────────────────────
Multi-language utilities for execution agents.

Provides:
  - LANGUAGE_CONFIG   : per-language greetings, sign-offs, script snippets
  - build_language_instruction()  : extra prompt instruction for Gemini
  - build_agent_context()         : injects RAG + customer memory into prompts
  - MOCK_TEMPLATES    : mock messages per channel × language

Supported languages (matching core.models.Language):
  english, hindi, marathi, bengali, tamil, telugu, kannada, malayalam, gujarati
"""

from __future__ import annotations

from typing import Optional

# ── Language metadata ─────────────────────────────────────────────────────────

LANGUAGE_CONFIG: dict[str, dict] = {
    "english": {
        "greeting":    "Dear {name}",
        "sign_off":    "Warm regards,\nSuraksha Life Insurance",
        "renew_cta":   "Renew Now",
        "urgency":     "Your policy is due for renewal.",
        "script_open": "Hello {name}, this is a call from Suraksha Life Insurance.",
        "native_name": "English",
        "script":      "Speak clearly in English. Use formal but warm tone.",
    },
    "hindi": {
        "greeting":    "प्रिय {name} जी",
        "sign_off":    "आपका शुभचिंतक,\nसुरक्षा लाइफ इंश्योरेंस",
        "renew_cta":   "अभी नवीनीकरण करें",
        "urgency":     "आपकी पॉलिसी का नवीनीकरण अपेक्षित है।",
        "script_open": "नमस्ते {name} जी, मैं सुरक्षा लाइफ इंश्योरेंस से बोल रहा/रही हूँ।",
        "native_name": "हिन्दी",
        "script":      "Write entirely in Hindi (Devanagari script). Use respectful 'aap' form.",
    },
    "marathi": {
        "greeting":    "प्रिय {name} जी",
        "sign_off":    "आपला विश्वासू,\nसुरक्षा लाइफ विमा",
        "renew_cta":   "आता नूतनीकरण करा",
        "urgency":     "आपल्या पॉलिसीचे नूतनीकरण आवश्यक आहे.",
        "script_open": "नमस्कार {name} जी, मी सुरक्षा लाइफ विम्याकडून बोलत आहे.",
        "native_name": "मराठी",
        "script":      "Write entirely in Marathi. Use polite 'aapan' form.",
    },
    "bengali": {
        "greeting":    "প্রিয় {name}",
        "sign_off":    "শুভেচ্ছায়,\nসুরক্ষা লাইফ ইন্স্যুরেন্স",
        "renew_cta":   "এখনই নবায়ন করুন",
        "urgency":     "আপনার পলিসির নবায়ন প্রয়োজন।",
        "script_open": "নমস্কার {name}, আমি সুরক্ষা লাইফ ইন্স্যুরেন্স থেকে ফোন করছি।",
        "native_name": "বাংলা",
        "script":      "Write entirely in Bengali (Bangla script). Use respectful 'aapni' form.",
    },
    "tamil": {
        "greeting":    "அன்புள்ள {name}",
        "sign_off":    "அன்புடன்,\nசுரக்ஷா லைஃப் இன்ஷூரன்ஸ்",
        "renew_cta":   "இப்போதே புதுப்பிக்கவும்",
        "urgency":     "உங்கள் பாலிசி புதுப்பிக்கப்பட வேண்டியுள்ளது.",
        "script_open": "வணக்கம் {name}, நான் சுரக்ஷா லைஃப் இன்ஷூரன்ஸிலிருந்து அழைக்கிறேன்.",
        "native_name": "தமிழ்",
        "script":      "Write entirely in Tamil script. Use respectful 'neengal' form.",
    },
    "telugu": {
        "greeting":    "ప్రియమైన {name}",
        "sign_off":    "మీ విశ్వాసపాత్రుడు,\nసురక్షా లైఫ్ ఇన్సూరెన్స్",
        "renew_cta":   "ఇప్పుడే పునరుద్ధరించండి",
        "urgency":     "మీ పాలసీ పునరుద్ధరణ అవసరం.",
        "script_open": "నమస్కారం {name}, నేను సురక్షా లైఫ్ ఇన్సూరెన్స్ నుండి మాట్లాడుతున్నాను.",
        "native_name": "తెలుగు",
        "script":      "Write entirely in Telugu script. Use respectful 'meeru' form.",
    },
    "kannada": {
        "greeting":    "ಆತ್ಮೀಯ {name}",
        "sign_off":    "ವಿಶ್ವಾಸದಿಂದ,\nಸುರಕ್ಷಾ ಲೈಫ್ ಇನ್ಶುರೆನ್ಸ್",
        "renew_cta":   "ಈಗಲೇ ನವೀಕರಿಸಿ",
        "urgency":     "ನಿಮ್ಮ ಪಾಲಿಸಿ ನವೀಕರಣ ಅಗತ್ಯ.",
        "script_open": "ನಮಸ್ಕಾರ {name}, ನಾನು ಸುರಕ್ಷಾ ಲೈಫ್ ಇನ್ಶುರೆನ್ಸ್ ನಿಂದ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ.",
        "native_name": "ಕನ್ನಡ",
        "script":      "Write entirely in Kannada script. Use respectful 'neevu' form.",
    },
    "malayalam": {
        "greeting":    "പ്രിയ {name}",
        "sign_off":    "സ്നേഹത്തോടെ,\nസുരക്ഷ ലൈഫ് ഇൻഷ്വറൻസ്",
        "renew_cta":   "ഇപ്പോൾ പുതുക്കുക",
        "urgency":     "നിങ്ങളുടെ പോളിസി പുതുക്കൽ ആവശ്യമാണ്.",
        "script_open": "നമസ്കാരം {name}, ഞാൻ സുരക്ഷ ലൈഫ് ഇൻഷ്വറൻസിൽ നിന്ന് വിളിക്കുന്നു.",
        "native_name": "മലയാളം",
        "script":      "Write entirely in Malayalam script. Use respectful 'ningal' form.",
    },
    "gujarati": {
        "greeting":    "પ્રિય {name}",
        "sign_off":    "આપનો વિશ્વાસુ,\nસુરક્ષા લાઇફ ઇન્સ્યોરન્સ",
        "renew_cta":   "હવે નવીકરણ કરો",
        "urgency":     "આપની પૉલિસી નવીકરણ જરૂરી છે.",
        "script_open": "નમસ્તે {name}, હું સુરક્ષા લાઇફ ઇન્સ્યોરન્સ તરફથી બોલી રહ્યો/રહ્યી છું.",
        "native_name": "ગુજરાતી",
        "script":      "Write entirely in Gujarati script. Use respectful 'aap' form.",
    },
}


def get_language_config(language: str) -> dict:
    """Get language config, fallback to English."""
    return LANGUAGE_CONFIG.get(language.lower(), LANGUAGE_CONFIG["english"])


def build_language_instruction(language: str, name: str = "") -> str:
    """
    Return a strong language instruction block to prepend to any agent prompt.
    This forces Gemini to generate in the correct language and script.
    """
    cfg  = get_language_config(language)
    lang = cfg["native_name"]

    if language.lower() == "english":
        return f"Write in English. Greeting: 'Dear {name}'. Sign off: 'Warm regards, Suraksha Life Insurance'."

    return (
        f"CRITICAL LANGUAGE INSTRUCTION:\n"
        f"Write ENTIRELY in {lang} ({language.title()} script). DO NOT use English except for:\n"
        f"  - Policy number, premium amounts (numerals), product name\n"
        f"  - Brand name 'Suraksha Life Insurance'\n"
        f"Use this greeting: {cfg['greeting'].format(name=name)}\n"
        f"Use this sign-off: {cfg['sign_off']}\n"
        f"CTA button text: {cfg['renew_cta']}\n"
        f"{cfg['script']}"
    )


def build_agent_context(
    customer_id: str,
    query:       str,
    channel:     str = "whatsapp",
) -> str:
    """
    Build a combined RAG + customer memory context block for agent prompts.
    This enriches every outbound message with:
      1. Relevant KB docs (objections, FAQs, scripts)
      2. Customer's interaction history summary
    """
    parts = []

    # 1. Customer memory
    try:
        from memory.customer_memory import CustomerMemoryStore
        mem     = CustomerMemoryStore()
        summary = mem.get_summary(customer_id)
        if summary and "No prior" not in summary:
            parts.append(f"CUSTOMER HISTORY:\n{summary}")
    except Exception:
        pass

    # 2. RAG knowledge
    try:
        from knowledge.rag_knowledge_base import RagKnowledgeBase
        kb  = RagKnowledgeBase()
        kb.build()
        ctx = kb.build_context(query, n=2)
        if ctx:
            parts.append(f"RELEVANT KNOWLEDGE:\n{ctx[:800]}")
    except Exception:
        pass

    if not parts:
        return ""

    return "\n\n".join(parts)


# ── Mock templates per language ───────────────────────────────────────────────

_MOCK_WHATSAPP: dict[str, str] = {
    "english":   "Dear {name}, your {product} policy ({policy_no}) is due for renewal on {due_date}. Amount: ₹{premium}. Renew now: {link}",
    "hindi":     "प्रिय {name} जी, आपकी {product} पॉलिसी ({policy_no}) का नवीनीकरण {due_date} को देय है। राशि: ₹{premium}। अभी नवीनीकरण करें: {link}",
    "marathi":   "प्रिय {name} जी, तुमच्या {product} पॉलिसी ({policy_no}) चे नूतनीकरण {due_date} रोजी आहे। रक्कम: ₹{premium}। आत्ता नूतनीकरण करा: {link}",
    "bengali":   "প্রিয় {name}, আপনার {product} পলিসি ({policy_no}) {due_date} তারিখে নবায়নযোগ্য। পরিমাণ: ₹{premium}। এখনই নবায়ন করুন: {link}",
    "tamil":     "அன்புள்ள {name}, உங்கள் {product} பாலிசி ({policy_no}) {due_date} அன்று புதுப்பிக்க வேண்டும். தொகை: ₹{premium}. இப்போதே புதுப்பிக்கவும்: {link}",
    "telugu":    "ప్రియమైన {name}, మీ {product} పాలసీ ({policy_no}) {due_date} న పునరుద్ధరణకు చెల్లుతుంది. మొత్తం: ₹{premium}. ఇప్పుడే పునరుద్ధరించండి: {link}",
    "kannada":   "ಆತ್ಮೀಯ {name}, ನಿಮ್ಮ {product} ಪಾಲಿಸಿ ({policy_no}) {due_date} ರಂದು ನವೀಕರಣಕ್ಕೆ ಅಗತ್ಯ. ಮೊತ್ತ: ₹{premium}. ಈಗಲೇ ನವೀಕರಿಸಿ: {link}",
    "malayalam": "പ്രിയ {name}, നിങ്ങളുടെ {product} പോളിസി ({policy_no}) {due_date} ന് പുതുക്കണം. തുക: ₹{premium}. ഇപ്പോൾ പുതുക്കുക: {link}",
    "gujarati":  "પ્રિય {name}, તમારી {product} પૉલિસી ({policy_no}) {due_date} ના રોજ નવીકરણ થવાની છે. રકમ: ₹{premium}. હવે નવીકરણ કરો: {link}",
}

_MOCK_EMAIL_SUBJECT: dict[str, str] = {
    "english":   "Action Required: Renew Your {product} Policy ({policy_no})",
    "hindi":     "कृपया ध्यान दें: अपनी {product} पॉलिसी ({policy_no}) का नवीनीकरण करें",
    "marathi":   "महत्त्वाचे: आपल्या {product} पॉलिसीचे नूतनीकरण करा ({policy_no})",
    "tamil":     "முக்கியமான அறிவிப்பு: உங்கள் {product} பாலிசியை புதுப்பிக்கவும் ({policy_no})",
    "telugu":    "ముఖ్యమైన సూచన: మీ {product} పాలసీ పునరుద్ధరించండి ({policy_no})",
    "bengali":   "গুরুত্বপূর্ণ: আপনার {product} পলিসি নবায়ন করুন ({policy_no})",
    "kannada":   "ಮಹತ್ವದ ಸೂಚನೆ: ನಿಮ್ಮ {product} ಪಾಲಿಸಿ ನವೀಕರಿಸಿ ({policy_no})",
    "malayalam": "പ്രധാനപ്പെട്ട അറിയിപ്പ്: നിങ്ങളുടെ {product} പോളിസി പുതുക്കുക ({policy_no})",
    "gujarati":  "મહત્ત્વની સૂચના: તમારી {product} પૉલિસી નવીકરણ કરો ({policy_no})",
}

_MOCK_VOICE_SCRIPT: dict[str, str] = {
    "english":   "Hello {name}, this is Suraksha Life Insurance calling about your {product} policy {policy_no} renewal due on {due_date}. The renewal amount is rupees {premium}. Shall I process it now?",
    "hindi":     "नमस्ते {name} जी, मैं सुरक्षा लाइफ इंश्योरेंस से बोल रहा हूँ। आपकी {product} पॉलिसी {policy_no} का नवीनीकरण {due_date} को देय है। राशि ₹{premium} है। क्या मैं अभी प्रक्रिया करूँ?",
    "marathi":   "नमस्कार {name} जी, मी सुरक्षा लाइफ विमाकडून बोलत आहे। तुमच्या {product} पॉलिसी {policy_no} चे नूतनीकरण {due_date} रोजी आहे। रक्कम ₹{premium} आहे.",
    "tamil":     "வணக்கம் {name}, நான் சுரக்ஷா லைஃப் இன்ஷூரன்ஸிலிருந்து அழைக்கிறேன். உங்கள் {product} பாலிசி {policy_no} {due_date} அன்று புதுப்பிக்க வேண்டும். தொகை ₹{premium}.",
    "telugu":    "నమస్కారం {name}, నేను సురక్షా లైఫ్ ఇన్సూరెన్స్ నుండి మాట్లాడుతున్నాను. మీ {product} పాలసీ {policy_no} {due_date} న పునరుద్ధరణకు ₹{premium} చెల్లుతుంది.",
    "bengali":   "নমস্কার {name}, আমি সুরক্ষা লাইফ ইন্স্যুরেন্স থেকে বলছি। আপনার {product} পলিসি {policy_no} {due_date} তারিখে নবায়নযোগ্য। পরিমাণ ₹{premium}।",
    "kannada":   "ನಮಸ್ಕಾರ {name}, ನಾನು ಸುರಕ್ಷಾ ಲೈಫ್ ಇನ್ಶುರೆನ್ಸ್ ನಿಂದ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ. ನಿಮ್ಮ {product} ಪಾಲಿಸಿ {policy_no} {due_date} ರಂದು ನವೀಕರಣ ₹{premium}.",
    "malayalam": "നമസ്കാരം {name}, ഞാൻ സുരക്ഷ ലൈഫ് ഇൻഷ്വറൻസിൽ നിന്ന് വിളിക്കുന്നു. നിങ്ങളുടെ {product} പോളിസി {policy_no} {due_date} ന് ₹{premium} പുതുക്കണം.",
    "gujarati":  "નમસ્તે {name}, હું સુરક્ષા લાઇફ ઇન્સ્યોરન્સ તરફથી બોલી રહ્યો છું. તમારી {product} પૉલિસી {policy_no} {due_date} ના રોજ ₹{premium} ની નવીકરણ બાકી છે.",
}


def get_mock_message(
    channel:  str,
    language: str,
    name:     str,
    product:  str,
    policy_no: str,
    due_date: str,
    premium:  str,
    link:     str = "https://pay.suraксhalife.com/renew",
    subject:  bool = False,
) -> str:
    """Return a language-appropriate mock message for the given channel."""
    lang = language.lower()

    if channel == "whatsapp" or channel == "sms":
        tmpl = _MOCK_WHATSAPP.get(lang, _MOCK_WHATSAPP["english"])
        return tmpl.format(name=name, product=product, policy_no=policy_no,
                           due_date=due_date, premium=premium, link=link)

    elif channel == "email":
        if subject:
            tmpl = _MOCK_EMAIL_SUBJECT.get(lang, _MOCK_EMAIL_SUBJECT["english"])
            return tmpl.format(product=product, policy_no=policy_no)
        # Email body = WhatsApp style for mock
        tmpl = _MOCK_WHATSAPP.get(lang, _MOCK_WHATSAPP["english"])
        return tmpl.format(name=name, product=product, policy_no=policy_no,
                           due_date=due_date, premium=premium, link=link)

    elif channel == "voice":
        tmpl = _MOCK_VOICE_SCRIPT.get(lang, _MOCK_VOICE_SCRIPT["english"])
        return tmpl.format(name=name, product=product, policy_no=policy_no,
                           due_date=due_date, premium=premium)

    return f"Renewal reminder for {name}: {policy_no} due {due_date}, ₹{premium}"
