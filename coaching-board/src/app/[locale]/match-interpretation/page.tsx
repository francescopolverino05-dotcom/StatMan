import type { Metadata } from "next";
import { PageIntro } from "../../../components/page-intro";
import { PhaseTabs } from "../../../components/phase-tabs";
import { matchInterpretation } from "../../../content/coaching";
import { tx } from "../../../content/i18n";
import { ui } from "../../../content/ui";
import { readLocale, type LocaleParams } from "../../../lib/params";

export async function generateMetadata({ params }: LocaleParams): Promise<Metadata> {
  const locale = await readLocale(params);
  return {
    title: tx(matchInterpretation.title, locale),
    description: tx(matchInterpretation.intro, locale),
  };
}

export default async function MatchInterpretationPage({ params }: LocaleParams) {
  const locale = await readLocale(params);

  const phases = matchInterpretation.phases.map((phase) => ({
    id: phase.id,
    title: tx(phase.title, locale),
    video: phase.video,
    videoCaption: phase.videoCaption ? tx(phase.videoCaption, locale) : null,
    moments: phase.moments.map((moment) => ({
      id: moment.id,
      title: tx(moment.title, locale),
      notes: moment.notes ? tx(moment.notes, locale) : null,
    })),
  }));

  return (
    <>
      <PageIntro
        locale={locale}
        title={tx(matchInterpretation.title, locale)}
        intro={tx(matchInterpretation.intro, locale)}
      />
      <section className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16">
        <PhaseTabs
          phases={phases}
          labels={{
            clip: tx(matchInterpretation.clipLabel, locale),
            textToCome: tx(ui.textToCome, locale),
            videoToCome: tx(ui.videoToCome, locale),
            playVideo: tx(ui.playVideo, locale),
          }}
        />
      </section>
    </>
  );
}
