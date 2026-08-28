/**
 * The public homepage at /.
 *
 * What it is for: someone arrives with no account and no context and needs to
 * learn, in one screen, what this thing measures, how it decides something is
 * wrong, and why they should believe the answer. Then it gets out of the way.
 *
 * Structure follows LoopSpill's front door — topbar, two-up hero with an
 * instrument panel, a pipeline strip, a hairline footer — so the two projects
 * read as one body of work. The palette does not: this is a wetland, not a
 * radar screen.
 *
 * WHAT IS DELIBERATELY NOT HERE
 *
 * No feature grid. The hero paragraph already says what the four pipeline steps
 * say; stating it twice on one screen is the shape a landing page falls into
 * when nobody decides what the page is for.
 *
 * No claim of official standing. This is a hackathon project about a Ramsar site,
 * not a government service, and the honesty strip says so in its own words rather
 * than burying it. The same strip names the synthetic data, because a visitor who
 * discovers that themselves on the map has been misled by the front page.
 *
 * No API call. A signed-out visitor has no session; a hero that degrades to a
 * blank box while a free Render instance wakes up is worse than an honest
 * diagram. Everything on this page is static.
 */
import { Link, useNavigate } from 'react-router-dom'

import { WetlandPanel } from '../components/landing/WetlandPanel'

/**
 * NOTE: this URL contains a personal account name. If the demo brief forbids
 * team or account names on screen, set it to null — the footer link drops out
 * and nothing else changes.
 */
const REPO_URL: string | null = 'https://github.com/raunaksahahere/LoopSatellite'

/**
 * How the system actually works, in the order it happens.
 *
 * Taken from what the code does rather than from a capability list: the water
 * index is a band ratio, the seasonal model is STL, the flagging is Seasonal-
 * Hybrid ESD, and the officer is the last step rather than an afterthought.
 */
const PIPELINE = [
  {
    step: '01',
    name: 'Measure',
    detail:
      'European Space Agency satellites photograph these wetlands every few days, ' +
      'and have for years. Each image is reduced to one number per pond per ' +
      'month: how much of it was still open water.',
  },
  {
    step: '02',
    name: 'Model the season',
    detail:
      'Every pond here shrinks in April and refills in August. Each one’s own ' +
      'rhythm is learned from its own history, so the question stops being “is it ' +
      'smaller?” and becomes “is it smaller than it should be this month?”',
  },
  {
    step: '03',
    name: 'Flag the outliers',
    detail:
      'Once the expected seasonal change is subtracted, what remains is tested ' +
      'against the pond’s own normal variation. A pond that dropped and came ' +
      'back is a dry season. One that dropped and stayed down is not, and that ' +
      'difference is the whole product.',
  },
  {
    step: '04',
    name: 'Build the case',
    detail:
      'Only now does a language model appear — to draft the report and the legal ' +
      'notice around a finding that already exists, with the provisions it cites ' +
      'retrieved from the actual statute text.',
  },
]

const FACTS = [
  {
    term: 'Statistics decides, not the model',
    detail:
      'No language model is on the path that determines whether a pond shrank. ' +
      'It writes about findings; it never makes one. A test walks the import ' +
      'graph and fails the build if that ever stops being true.',
  },
  {
    term: 'Some data here is synthetic',
    detail:
      'Real satellite measurements and synthetic ponds are both present, and the ' +
      'app never blurs the two. Every screen carries a banner when it is showing ' +
      'demonstration data, and the data sources page names each layer.',
  },
  {
    term: 'Not an official service',
    detail:
      'A student project about the East Kolkata Wetlands, a Ramsar site under ' +
      'genuine pressure. It has no regulatory standing, and a drafted notice is ' +
      'a starting point for a human, never something to send.',
  },
]

export function LandingPage() {
  const navigate = useNavigate()
  const enter = () => navigate('/welcome', { state: { from: '/map' } })

  return (
    <div className="landing">
      <header className="landing__topbar">
        <p className="landing__wordmark">
          <span className="landing__wordmark-mark" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          LoopSatellite
        </p>
        <button type="button" className="landing__navcta" onClick={enter}>
          Open the console
        </button>
      </header>

      <main className="landing__hero">
        <div className="landing__copy">
          <h1 className="landing__headline">
            Every wetland pond shrinks in April. Only some of them were filled in.
          </h1>

          <p className="landing__lead">
            LoopSatellite watches the water in the East Kolkata Wetlands from
            orbit and tells those two apart. It learns each pond’s own seasonal
            rhythm from years of satellite imagery, then flags the ones that lost
            water when they shouldn’t have — and never came back.
          </p>

          <div className="landing__actions">
            <button type="button" className="landing__enter" onClick={enter}>
              Open the console
            </button>
            <Link className="landing__secondary" to="/data-sources">
              See the data
            </Link>
          </div>

          <p className="landing__rule-line">
            <span aria-hidden="true">/</span> Statistics detects. The language
            model only builds the case around a finding statistics has already
            made — it never decides that a pond shrank.
          </p>
        </div>

        <WetlandPanel />
      </main>

      <section className="landing__flow" aria-labelledby="flow-title">
        <h2 className="landing__flow-title" id="flow-title">
          How it works
        </h2>
        <ol className="landing__steps">
          {PIPELINE.map((s) => (
            <li className="landing__step" key={s.step}>
              <span className="landing__step-no" aria-hidden="true">
                {s.step}
              </span>
              <h3 className="landing__step-name">{s.name}</h3>
              <p className="landing__step-detail">{s.detail}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing__facts" aria-label="What to know before you trust this">
        {FACTS.map((f) => (
          <dl className="landing__fact" key={f.term}>
            <dt>{f.term}</dt>
            <dd>{f.detail}</dd>
          </dl>
        ))}
      </section>

      <footer className="landing__footer">
        <span className="landing__footer-mark">LoopSatellite</span>
        {REPO_URL && (
          <a
            className="landing__footer-link"
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
          >
            Source on GitHub
          </a>
        )}
      </footer>
    </div>
  )
}
