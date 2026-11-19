import type { Metadata } from "next";
import { IdentityBoard } from "../../../components/identity-board";
import { PageIntro } from "../../../components/page-intro";
import { identity } from "../../../content/coaching";
import { tx } from "../../../content/i18n";
import { ui } from "../../../content/ui";
import { readLocale, type LocaleParams } from "../../../lib/params";

export async function generateMetadata({ params }: LocaleParams): Promise<Metadata> {
  const locale = await readLocale(params);
  return { title: tx(identity.title, locale), description: tx(identity.intro, locale) };
}

export default async function PlayerIdentityPage({ params }: LocaleParams) {
  const locale = await readLocale(params);

  const roles = identity.roles.map((role) => ({
    id: role.id,
    title: tx(role.title, locale),
    spots: role.spots,
    facets: [
      { label: tx(identity.withBallLabel, locale), text: role.withBall ? tx(role.withBall, locale) : null },
      {
        label: tx(identity.withoutBallLabel, locale),
        text: role.withoutBall ? tx(role.withoutBall, locale) : null,
      },
      {
        label: tx(identity.characterLabel, locale),
        text: role.character ? tx(role.character, locale) : null,
      },
    ],
  }));

  return (
    <>
      <PageIntro locale={locale} title={tx(identity.title, locale)} intro={tx(identity.intro, locale)} />
      <section className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16">
        <IdentityBoard
          roles={roles}
          labels={{
            pick: tx(identity.pickLabel, locale),
            textToCome: tx(ui.textToCome, locale),
            formation: `${tx(identity.formationLabel, locale)} ${identity.formation}`,
          }}
        />
      </section>
    </>
  );
}
