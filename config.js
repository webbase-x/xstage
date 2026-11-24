window.XSTAGE_CONFIG = {
  googleClientId: '231441301331-ti4139ajli0ormnc2lpkedlbcamsvgpm.apps.googleusercontent.com',
  googleAppId: '231441301331',
  // Required for Google Picker (shared-library onboarding). Restrict this key
  // to https://webbase-x.github.io/* and https://docs.google.com/*,
  // and to Google Picker API + Google Drive API.
  googlePickerApiKey: 'AIzaSyDbFTXZX8GuWMct5KhkviVg5t1Iff2nYoY'
};
// Explicitly retired Google Drive library. Never select, read or upload here.
window.XSTAGE_RETIRED_DRIVE_ROOT_IDS=Object.freeze(['1RYekUHCC3qs661cUrbxkNauUz_SuqZvy']);
window.XSTAGE_DRIVE_LAYOUT=Object.freeze({
  root:'XStageKaraoke',songs:'SONGS',db:'DB',
  soundfont:'SOUNDFONT',fx:'FX',backup:'BACKUP',cache:'CACHE',logs:'LOGS'
});
// The karaoke HTML owns its running build; config is only a fallback for other pages.
if (!window.XSTAGE_RELEASE) window.XSTAGE_RELEASE = { version: '1.0.213', build: 1213 };
