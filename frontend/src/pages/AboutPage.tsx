// About: Sanjana's essay, verbatim (her voice, her caps, her typos; please don't "clean it up"), then "Meet the Team
// Behind Bee Fit" (Sanjana and Summer, bios verbatim), then her own "HUGE disclaimer" paragraph styled as the page's
// disclaimer box. The site-wide footer disclaimer and /legal carry the full medical disclaimer regardless.
// The live data and sources section lives on its own page now: /about/data (AboutDataPage.tsx).
import { useState } from 'react'
import Link from '../components/Link'

const TEAM_PHOTOS = '/content/images/team'
const PHOTO_EXTS = ['jpg', 'png', 'webp']

// Photo files go in content/images/team/ (see its README): <file>.jpg, .png or .webp.
const SUMMER_PHOTOS: { file: string; alt: string }[] = [
  { file: 'summer-1', alt: 'Summer throwing a punch at pads held by her Muay Thai coach in Thailand' },
  { file: 'summer-2', alt: 'Summer with her guard up, facing her coach at a Muay Thai gym' },
  { file: 'summer-3', alt: 'Summer landing a jab on a focus mitt' },
  { file: 'summer-4', alt: 'Summer in a lunge, punching into her coach’s body shield' },
]

/** Tries file.jpg, .png, .webp; shows a drawn placeholder until one exists (never a broken image). */
function TeamPhoto({ file, alt, className }: { file: string; alt: string; className: string }) {
  const [attempt, setAttempt] = useState(0)
  if (attempt >= PHOTO_EXTS.length) {
    return (
      <div className={`${className} team-photo-empty`} role="img" aria-label={`${alt} (photo coming soon)`}>
        <svg viewBox="0 0 64 64" aria-hidden="true">
          <circle cx="32" cy="24" r="12" />
          <path d="M10 58c2-13 11-20 22-20s20 7 22 20z" />
        </svg>
      </div>
    )
  }
  return (
    <img
      className={className}
      src={`${TEAM_PHOTOS}/${file}.${PHOTO_EXTS[attempt]}`}
      alt={alt}
      loading="lazy"
      onError={() => setAttempt((a) => a + 1)}
    />
  )
}

/** "Meet the Team Behind Bee Fit": Sanjana (photo left, text right) and Summer (four photos, then text). */
function Team() {
  return (
    <section className="about-team" aria-labelledby="team-title">
      <h3 id="team-title" className="team-title">
        Meet the Team Behind Bee Fit
      </h3>

      {/* Bios verbatim, 2026-10-25. Please don't edit the wording. */}
      <article className="team-profile team-profile-side">
        <TeamPhoto
          file="sanjana"
          alt="Sanjana smiling, in a navy Yale School of Management quarter-zip"
          className="team-photo team-photo-portrait"
        />
        <div className="team-profile-text">
          <h4>Sanjana C, the vibe-coder.</h4>
          <p>
            Sanjana C is not a programmer. Sanjana C is a business student at Yale, likes working out, and likes
            simplifying things. As all good b-school students do, Sanjana started her career in consulting before
            working in strategy at a community college in Chicago. This is not super important context for the app, but
            all to say, Sanjana likes making things work better, wants people to be healthy and happy and with endorphins
            so they don't kill their husbands, and wants to work in inclusive economic development and the public sector
            long-term. Sanjana's bff is Summer, who she goes to for all things fitness advice. Read about Summer below.
          </p>
        </div>
      </article>

      <article className="team-profile">
        <div className="team-photo-grid">
          {SUMMER_PHOTOS.map((ph) => (
            <TeamPhoto key={ph.file} file={ph.file} alt={ph.alt} className="team-photo team-photo-tall" />
          ))}
        </div>
        <div className="team-profile-text">
          <h4>Summer A, your new personal trainer.</h4>
          <p>
            Summer's idea of a relaxing vacation? Flying to Thailand for a month to learn Muay Thai and get into actual
            fights (see photographic evidence above). Fortunately, her coaching style is far less intimidating. A
            competitive tennis player since childhood, fitness has basically been Summer's entire personality for as long
            as she can remember. Armed with an alphabet of credentials (ACE Personal Trainer, Power Pilates Mat
            Instructor, and PTR Level 1 Coach) her true superpower is making fitness genuinely fun, accessible, and
            welcoming. She is fiercely dedicated to helping folks whose bodies aren't traditionally represented in
            fitness spaces find joy in movement. Whether you're on the court, on the mat, or in the gym, Summer is here to
            prove that working out can be enjoyable (no international cage matches required).
          </p>
        </div>
      </article>
    </section>
  )
}

export default function AboutPage() {
  return (
    <article className="about">
      <h2 className="page-title">About Bee Fit</h2>

      <div className="about-essay">
        <p>
          Omg!! Guys, I literally vibe-coded this entire site for my Yale SOM AI Foundations class. I'm shook to my
          core.
        </p>

        <p>
          So this was our final project for the class, and – also, hi, I'm Sanjana, first-year MBA at Yale SOM (and,
          must add, ardent Buckeye as an Ohio State undergrad) – and I've been thinking about an idea like this for a
          while. Come hear my grievances about working out:
        </p>

        <ul>
          <li>I like working out. I feel good working out.</li>
          <li>
            What I don't like about working out is the MENTAL LOAD. Like. You're telling me I have to not only motivate
            myself to leave my apartment and go to the gym and wear cute workout clothes – and I don't think my workout
            clothes are that cute so sometimes that's a whole battle and also sometimes I don't want to leave the house
            because I literally cannot deal with seeing a single other soul after hours of #networking – but first I
            have to eat a snack and debate how starving I am after and if I have time to cook and then if I can't get
            to the gym in time then I can't cook – and it's just like, okay, on top of all of this, I have to THINK
            ABOUT MY WORKOUT? I can't. Literally cannot.
          </li>
          <li>
            I suppose they all say consistency is key? But you better not expect me to be writing down my workouts. In
            the economy????
          </li>
          <li>
            I need flexibility. I really need to be able to have some at-home workouts and some where I actually go to
            the gym and use machines. I need short times sometimes and longer times others. And I need something to
            hold the mental weight of my working out.
          </li>
          <li>
            Also, at the unripe age of 28, my body hurts. My back hurts and the other day I did my old workout routine
            from like 10 years ago and my back hurt moreeee. I've been in PT, graduated, and yet, it's still hard to
            actually find a workout app that works for your body.
          </li>
          <li>
            I'm also broke now, and these pilates studios will deadass look you in the eye and tell you that their
            classes are $55/session. In this economy????
          </li>
          <li>
            Also, I sort of only want to play sports. Like, actual things that are fun. I joined a soccer league last
            year, and it was so fun (we lost every game), and after every game my entire team was unable to move. So,
            like, to do the fun life things, you have to strength train.
          </li>
          <li>
            And, guys, I begged my women's health friends to all tell me differently but their consensus was
            unequivocal: women, especially women over 30, simply must strength train. I'm sorry. I wish it were
            different, too.
          </li>
          <li>
            Okay, sorry, I had to ask the AI to strip out all of my stream of consciousness and my personality for the
            rest of this app so it's not all this lengthy. Tl;dr: I needed a free workout app that allowed me to meet my
            goals while taking into consideration my injuries, time constraints, home workout materials and – most
            critically – once I set it, would just push me to stick to it.
          </li>
        </ul>

        <p>So here we are! That's my app.</p>

        {/* Verbatim, 2026-10-25. Please don't edit the wording. */}
        <p>
          I feel super not qualified to actually give advice on fitness. Thankfully, my best friend/platonic life
          partner (Summer) is in the industry – she's a personal trainer and pilates instructor, and she helped me make
          sure this app is based on real stuff that works and is not just generated by an AI without considering
          workout science. In the future, I'd love to have a few other health / fitness professionals working on this
          app with me – Summer's mom is a physical therapist, and my sister is a literal OB/GYN (talk about one kid
          with no skills and one kid who's overskilled, right). I'm hoping we can apply a physical therapy lens to the
          AI-drafted injuries, and I'm hoping we can apply a women's health/pregnancy lens to fitness as well.
        </p>
      </div>

      <Team />

      <div className="about-essay">
        {/* Her own disclaimer, in her words, gets the site's disclaimer-box treatment (design.md 7 rule 1). */}
        <section className="class-disclaimer" role="note" aria-label="Disclaimer">
          <p>
            HUGE disclaimer. THIS IS A CLASS PROJECT. Think about your class projects. There are things here that aren't
            fully reviewed and none of this has been verified by a legit, non-vibe-coding programmer. There are flaws,
            it will be buggy, and the health data is IN PROGRESS. If this somehow takes off, then sure, I'll make sure
            we actually work through all health verifications, injury verifications, etc. But guys, it's 40% of my
            class grade at a program that doesn't do grade disclosures. So I'm proud of my work, but to be so real,
            it's not perfect.
          </p>
          <Link to="/legal">Read the full medical disclaimer, privacy and legal page</Link>
        </section>

        <p>
          Okay, that's about it. Email me with whatever if you guys have thoughts or want any changes. If they're easy
          enough, I'll make them. If they're hard, Venmo me. ;)
        </p>
      </div>

      <p className="about-data-link">
        <Link to="/about/data">Curious where our data comes from? See the live numbers and every source we use →</Link>
      </p>
    </article>
  )
}
