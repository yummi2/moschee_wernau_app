(() => {
  const language = localStorage.getItem("registrationLanguage") === "de" ? "de" : "ar";
  window.registrationLanguage = language;

  const translations = {
    "مرحبًا بك في": "Herzlich willkommen bei",
    "دار الفرح": "Dar Al Farah",
    "مساحتك لمتابعة الواجبات والأنشطة والتقدم الدراسي بسهولة.": "Dein Bereich für Hausaufgaben, Aktivitäten und Lernfortschritt.",
    "تسجيل الدخول": "Anmelden",
    "التسجيل الجديد": "Neue Anmeldung",
    "للعام الدراسي 2026/2027": "Für das Schuljahr 2026/2027",
    "أهلًا وسهلًا": "Herzlich willkommen",
    "اسم المستخدم": "Benutzername",
    "كلمة المرور": "Passwort",
    "اسم المستخدم أو كلمة المرور غير صحيحة. حاول مرة أخرى.": "Benutzername oder Passwort ist falsch. Bitte versuchen Sie es erneut.",
    "دخول": "Einloggen",
    "اضغط على البطاقة للتسجيل.": "Klicke auf die Karte, um dein Kind anzumelden.",
    "ضع صورة التسجيل هنا": "Anmeldebild hier einfügen",
    "مرحبًا بكم في دار الفرح": "Herzlich willkommen bei Dar Al Farah",
    "شروط التسجيل في الدورة التعليمية في مسجد فيرناو للعام الدراسي 2027 /2026": "Anmeldebedingungen für den Unterricht in der Moschee Wernau im Schuljahr 2026/2027",
    "يرجى قراءة الشروط التالية كاملة قبل المتابعة.": "Bitte lesen Sie alle Bedingungen vollständig, bevor Sie fortfahren.",
    "مرّر إلى نهاية النص لتفعيل زر الموافقة.": "Scrollen Sie bis zum Ende, um die Zustimmung zu aktivieren.",
    "موافق": "Einverstanden",
    "طلب تسجيل جديد": "Neue Anmeldung",
    "بيانات الطالب": "Daten des Kindes",
    "يرجى تعبئة البيانات التالية لكل طالب على حدى": "Bitte füllen Sie die folgenden Angaben für jedes Kind einzeln aus.",
    "اسم العائلة": "Nachname",
    "الاسم الأول": "Vorname",
    "الصف الدراسي في المدرسة الألمانية": "Klasse in der deutschen Schule",
    "تاريخ الميلاد": "Geburtsdatum",
    "اختر تاريخ الميلاد": "Geburtsdatum auswählen",
    "فتح التقويم": "Kalender öffnen",
    "اختر سنة الميلاد": "Geburtsjahr auswählen",
    "اختر شهر الميلاد": "Geburtsmonat auswählen",
    "السنة": "Jahr",
    "الشهر": "Monat",
    "العنوان": "Adresse",
    "اسم الشارع": "Straßenname",
    "رقم المنزل": "Hausnummer",
    "الرمز البريدي": "PLZ",
    "المدينة": "Stadt",
    "رقم الهاتف": "Handynummer",
    "مثال:01234567891 ، 01234567891": "Beispiel: 01234567891, 01234567891",
    "يمكن إدخال رقم أو رقمين وعند إضافة رقم ثانٍ افصل بينهما بفاصلة.": "Sie können eine oder zwei Nummern eingeben. Trennen Sie eine zweite Nummer mit einem Komma.",
    "البريد الإلكتروني": "E-Mail-Adresse",
    "أسمح بتصوير ابني واستخدام الصور والفيديوهات": "Ich erlaube, mein Kind zu fotografieren und Fotos oder Videos zu verwenden",
    "نعم": "Ja",
    "لا": "Nein",
    "يمكنك اختيار الخيارين معًا": "Sie können beide Optionen auswählen.",
    "فيديو المدرسة": "Schulvideo",
    "إنستغرام": "Instagram",
    "أريد تسجيل ابني بـ": "Ich möchte mein Kind anmelden für",
    "دروس اللغة العربية والدروس الدينية": "Arabisch- und Religionsunterricht",
    "لكل فصل دراسي 225 يورو": "225 Euro pro Schulhalbjahr",
    "الدروس الدينية فقط": "Nur Religionsunterricht",
    "لكل فصل دراسي 150 يورو": "150 Euro pro Schulhalbjahr",
    "اللغة العربية فقط": "Nur Arabischunterricht",
    "إرسال طلب التسجيل": "Anmeldung absenden",
    "تم إرسال الطلب بنجاح": "Anmeldung erfolgreich gesendet",
    "تم تسجيل طفلك للعام الدراسي القادم": "Ihr Kind wurde für das kommende Schuljahr angemeldet",
    "إذا أردت تسجيل طفل آخر، سوف يُمنح الطفل الثاني خصماً بنسبة 10%، والطفل الثالث خصماً بنسبة 20%.": "Wenn Sie ein weiteres Kind anmelden, erhält das zweite Kind 10 % und das dritte Kind 20 % Ermäßigung.",
    "تسجيل طفل آخر": "Weiteres Kind anmelden",
    "العودة إلى تسجيل الدخول": "Zurück zur Anmeldung",
    "فتح معلومات التسجيل للعام القادم": "Anmeldeinformationen für das kommende Schuljahr öffnen",
    "إعلان التسجيل للعام الدراسي القادم": "Ankündigung zur Anmeldung für das kommende Schuljahr"
  };

  const root = document.querySelector(".login-page, .registration-info-page");
  if (!root) return;
  root.dir = language === "de" ? "ltr" : "rtl";
  root.lang = language;
  root.classList.toggle("is-german", language === "de");
  if (language === "de") {
    document.title = root.classList.contains("login-page") ? "Anmelden | Dar Al Farah" : "Neue Anmeldung | Dar Al Farah";
  }
  root.querySelectorAll('input[name="ui_language"]').forEach((input) => { input.value = language; });

  document.querySelectorAll("[data-registration-language]").forEach((button) => {
    button.setAttribute("aria-pressed", String(language === "de"));
    const label = button.querySelector("span");
    if (label) label.textContent = language === "de" ? "العربية" : "Deutsch";
    button.addEventListener("click", () => {
      localStorage.setItem("registrationLanguage", language === "de" ? "ar" : "de");
      window.location.reload();
    });
  });

  document.querySelectorAll("[data-language-content]").forEach((element) => {
    element.hidden = element.dataset.languageContent !== language;
  });

  if (language !== "de") return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    if (node.parentElement?.closest('[data-language-content="ar"]')) return;
    const value = node.nodeValue.trim();
    if (!translations[value]) return;
    node.nodeValue = node.nodeValue.replace(value, translations[value]);
  });

  root.querySelectorAll("[placeholder], [aria-label], [title]").forEach((element) => {
    ["placeholder", "aria-label", "title"].forEach((attribute) => {
      const value = element.getAttribute(attribute);
      if (value && translations[value]) element.setAttribute(attribute, translations[value]);
    });
  });
})();
