// All legal / privacy text in one place, bundled into the page so it shows
// even if the backend is down.

// Bump this whenever the disclaimer text below changes; it's stored with each
// user's consent so we know which version they accepted.
export const CONSENT_VERSION = '2026-10-22'

export const DISCLAIMER =
  'Bee Fit is a student project and is not a substitute for professional medical advice. ' +
  'Consult a doctor or physical therapist before starting any exercise program, especially if you ' +
  'have an injury or medical condition.'

// The OB-GYN who recorded the pregnancy/postpartum message (content/video/obgyn_pregnancy_message.mp4).
// Placeholder: swap in the real name.
export const OBGYN_NAME = 'Dr. [Name]'

export const CLASS_PROJECT_NOTE =
  'Bee Fit is a class project, not a commercial product. Use it at your own risk.'

// Shown as the required acknowledgment step in the quiz, before any health questions.
export const DISCLAIMER_FULL_POINTS = [
  'The workouts, programs, and tips here are general information. Even when they take the injuries you report into account, they are not personalized medical advice from a professional who has examined you.',
  'Much of the content is still pending review by a physical therapist or doctor.',
  'Stop exercising and get medical care if you feel sharp or sudden pain, numbness, tingling, chest pain, dizziness, or trouble breathing.',
  'You use Bee Fit at your own risk.',
]

export const CONSENT_LABEL =
  'I have read and understand this disclaimer. I will check with a doctor or physical therapist ' +
  "if I'm unsure whether an exercise is safe for me."

// Plain-language data practices: shown at signup, in Settings, and on /legal.
export const PRIVACY_POINTS: { heading: string; text: string }[] = [
  {
    heading: 'What we store',
    text: 'Your username, your first name (only to greet you on your Dashboard), and a scrambled (hashed) password; or, if you continue with Google or Microsoft, your email address (only when they confirm it is yours), your first name and an account id from them, so the same account signs you in next time (never your Google or Microsoft password); your quiz answers (your goal, experience, equipment, injuries, pregnancy or postpartum status, and, only if your goal is losing weight, your weight and an optional goal weight); your favorite exercises; the workouts and measurements you log; and, if you describe symptoms we redirect to a professional, the words that triggered it.',
  },
  {
    heading: 'Why',
    text: 'Only to run this class project. We do not sell your data or share it with third parties, with one exception below.',
  },
  {
    heading: 'AI features',
    text: 'Your weekly plan is built by our own code, not by AI. To explain it and to coach you, the app sends your goal, experience level and injury areas, plus the exercises in your plan, to an AI model provider (OpenAI, through the Portkey gateway). Your username, first name, email address, weight, goal weight, pregnancy or postpartum status, and anything you type in your own words are never sent.',
  },
  {
    heading: 'Deleting your data',
    text: 'Go to Settings and choose "Delete my data". That permanently deletes your account and everything listed above, right away. We keep only anonymous AI usage counts (how many tokens each AI feature used, no content), with the link to your account removed.',
  },
]
