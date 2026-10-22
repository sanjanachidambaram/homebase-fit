// All legal / privacy text in one place, bundled into the page so it shows
// even if the backend is down.

// Bump this whenever the disclaimer text below changes; it's stored with each
// user's consent so we know which version they accepted.
export const CONSENT_VERSION = '2026-10-22'

export const DISCLAIMER =
  'HomeBase Fit is a student project and is not a substitute for professional medical advice. ' +
  'Consult a doctor or physical therapist before starting any exercise program, especially if you ' +
  'have an injury or medical condition.'

export const CLASS_PROJECT_NOTE =
  'HomeBase Fit is a class project, not a commercial product. Use it at your own risk.'

// Shown as the required acknowledgment step in the quiz, before any health questions.
export const DISCLAIMER_FULL_POINTS = [
  'The workouts, programs, and tips here are general information. Even when they take the injuries you report into account, they are not personalized medical advice from a professional who has examined you.',
  'Much of the content is still pending review by a physical therapist or doctor.',
  'Stop exercising and get medical care if you feel sharp or sudden pain, numbness, tingling, chest pain, dizziness, or trouble breathing.',
  'You use HomeBase Fit at your own risk.',
]

export const CONSENT_LABEL =
  'I have read and understand this disclaimer. I will check with a doctor or physical therapist ' +
  "if I'm unsure whether an exercise is safe for me."

// Plain-language data practices: shown at signup, in Settings, and on /legal.
export const PRIVACY_POINTS: { heading: string; text: string }[] = [
  {
    heading: 'What we store',
    text: 'Your email and a scrambled (hashed) password; your quiz answers (goals, timeline, injuries, age, weight, height); your favorite exercises; the workouts and measurements you log; and, if you describe symptoms we redirect to a professional, the words that triggered it.',
  },
  {
    heading: 'Why',
    text: 'Only to run this class project. We do not sell your data or share it with third parties, with one exception below.',
  },
  {
    heading: 'AI features',
    text: 'To personalize plans, the app sends your goals, injury areas, timeline, age, weight, and height to an AI model provider (OpenAI, through the Portkey gateway). Your email, name, and any notes you type are never sent.',
  },
  {
    heading: 'Deleting your data',
    text: 'Go to Settings and choose "Delete my data". That permanently deletes your account and everything listed above, right away.',
  },
]
