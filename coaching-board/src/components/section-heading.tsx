export function SectionHeading({
  kicker,
  title,
  intro,
}: {
  kicker?: string;
  title: string;
  intro?: string;
}) {
  return (
    <div className="border-l-4 border-gold-deep pl-5">
      {kicker ? (
        <p className="text-[11px] font-medium tracking-[0.18em] text-gold-deep uppercase">
          {kicker}
        </p>
      ) : null}
      <h2 className="mt-2 text-4xl text-foreground sm:text-5xl">{title}</h2>
      {intro ? (
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-muted-foreground">{intro}</p>
      ) : null}
    </div>
  );
}
