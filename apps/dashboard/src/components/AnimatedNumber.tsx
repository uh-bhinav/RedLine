import CountUpModule from "react-countup";

// react-countup is CommonJS: depending on how Vite pre-bundles it, the default
// import arrives either as the component or wrapped in { default }. Unwrap.
const CountUp = ((CountUpModule as unknown as { default?: typeof CountUpModule }).default ??
  CountUpModule) as typeof CountUpModule;

/** Count-up number animation. `preserveValue` animates from the previous value on updates. */
export function AnimatedNumber({
  value,
  decimals = 0,
  suffix,
  duration = 0.8,
}: {
  value: number;
  decimals?: number;
  suffix?: string;
  duration?: number;
}) {
  return <CountUp end={value} decimals={decimals} duration={duration} suffix={suffix} preserveValue />;
}
