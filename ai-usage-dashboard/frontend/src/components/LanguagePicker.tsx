import { changeLanguage, languages, t, useLanguage } from '../i18n';

export function LanguagePicker() {
  const language = useLanguage();
  return (
    <select aria-label={t('界面语言')} title={t('界面语言')} value={language}
      onChange={(event) => changeLanguage(event.target.value)}>
      {Object.entries(languages).map(([code, name]) => <option key={code} lang={code} value={code}>{name}</option>)}
    </select>
  );
}
