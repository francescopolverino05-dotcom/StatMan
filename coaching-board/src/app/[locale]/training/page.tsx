import type { Metadata } from "next";
import { ArrowDown, ArrowRight } from "lucide-react";
import { PageIntro } from "../../../components/page-intro";
import { Pending } from "../../../components/pending";
import { VideoFrame } from "../../../components/video-frame";
import { training } from "../../../content/coaching";
import { tx } from "../../../content/i18n";
import { ui } from "../../../content/ui";
import { readLocale, type LocaleParams } from "../../../lib/params";

export async function generateMetadata({ params }: LocaleParams): Promise<Metadata> {
  const locale = await readLocale(params);
  return { title: tx(training.title, locale), description: tx(training.intro, locale) };
}

export default async function TrainingPage({ params }: LocaleParams) {
  const locale = await readLocale(params);
  const videoLabels = {
    emptyLabel: tx(ui.videoToCome, locale),
    playLabel: tx(ui.playVideo, locale),
  };

  return (
    <>
      <PageIntro locale={locale} title={tx(training.title, locale)} intro={tx(training.intro, locale)} />

      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        {training.drills.map((drill, index) => {
          const title = tx(drill.title, locale);
          const points = drill.coachingPoints.filter((point) => point !== null);
          return (
            <article
              key={drill.id}
              id={drill.id}
              className="border-b border-line py-12 last:border-b-0 sm:py-16"
            >
              <div className="grid gap-8 lg:grid-cols-[2fr_3fr]">
                <div className="dossier-rule pt-5">
                  <p className="text-[11px] font-medium tracking-[0.18em] text-gold-deep uppercase">
                    0{index + 1}
                  </p>
                  <h2 className="mt-2 text-3xl leading-tight text-foreground">{title}</h2>
                  <dl className="mt-5 flex flex-wrap gap-2">
                    {drill.setup.map((item) => (
                      <div
                        key={item.label.en}
                        className="rounded-lg border border-line bg-card px-3 py-2"
                      >
                        <dt className="text-[10px] font-medium tracking-[0.16em] text-gold-deep uppercase">
                          {tx(item.label, locale)}
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">{tx(item.value, locale)}</dd>
                      </div>
                    ))}
                  </dl>
                </div>

                <div className="grid gap-6 sm:grid-cols-2">
                  <div>
                    <h3 className="text-[11px] font-medium tracking-[0.16em] text-gold-deep uppercase [font-family:var(--font-sans)]">
                      {tx(training.objectiveLabel, locale)}
                    </h3>
                    {drill.objective ? (
                      <p className="mt-2 text-[15px] leading-relaxed text-foreground">
                        {tx(drill.objective, locale)}
                      </p>
                    ) : (
                      <Pending locale={locale} className="mt-2" />
                    )}
                  </div>
                  <div>
                    <h3 className="text-[11px] font-medium tracking-[0.16em] text-gold-deep uppercase [font-family:var(--font-sans)]">
                      {tx(training.pointsLabel, locale)}
                    </h3>
                    {points.length > 0 ? (
                      <ul className="mt-2 space-y-1.5 text-[15px] leading-relaxed text-foreground">
                        {points.map((point) => (
                          <li key={point.en} className="flex gap-2">
                            <span className="mt-2.5 size-1 shrink-0 rounded-full bg-gold" aria-hidden="true" />
                            {tx(point, locale)}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <Pending locale={locale} className="mt-2" />
                    )}
                  </div>
                </div>
              </div>

              <div className="mt-8 grid items-start gap-4 rounded-2xl bg-ink p-4 sm:p-6 md:grid-cols-[1fr_auto_1fr]">
                <figure>
                  <figcaption className="mb-3 text-[11px] font-medium tracking-[0.18em] text-gold uppercase">
                    {tx(training.trainingLabel, locale)}
                  </figcaption>
                  <VideoFrame
                    link={drill.trainingVideo}
                    title={`${title}: ${tx(training.trainingLabel, locale)}`}
                    {...videoLabels}
                  />
                </figure>
                <div
                  className="flex items-center justify-center self-center text-gold md:pt-7"
                  aria-hidden="true"
                >
                  <span className="flex size-10 items-center justify-center rounded-full border border-gold/40">
                    <ArrowRight className="hidden size-5 md:block" />
                    <ArrowDown className="size-5 md:hidden" />
                  </span>
                </div>
                <figure>
                  <figcaption className="mb-3 text-[11px] font-medium tracking-[0.18em] text-gold uppercase">
                    {tx(training.matchLabel, locale)}
                  </figcaption>
                  <VideoFrame
                    link={drill.matchVideo}
                    title={`${title}: ${tx(training.matchLabel, locale)}`}
                    {...videoLabels}
                  />
                  {drill.matchNote ? (
                    <p className="mt-3 text-sm leading-relaxed text-white/75">
                      {tx(drill.matchNote, locale)}
                    </p>
                  ) : null}
                </figure>
              </div>
            </article>
          );
        })}
      </div>
    </>
  );
}
