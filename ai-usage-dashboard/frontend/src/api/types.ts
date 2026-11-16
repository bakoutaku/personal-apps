import type { components } from './schema.gen';

type S = components['schemas'];

export type Meta = S['Meta'];
export type Page = S['Page'];
export type Account = S['Account'];
export type Health = S['Health'];
export type Source = S['Source'];
export type SourceErrorCode = S['SourceErrorCode'];
export type CoverageInterval = S['CoverageInterval'];
export type QuotaPool = S['QuotaPool'];
export type QuotaWindow = S['QuotaWindow'];
export type QuotaSnapshot = S['QuotaSnapshot'];
export type QuotaWindowSummary = S['QuotaWindowSummary'];
export type UsageSeries = S['UsageSeries'];
export type UsageBucket = S['UsageBucket'];
export type UsageEvent = S['UsageEvent'];
export type Session = S['Session'];
export type Label = S['Label'];
export type RangeTarget = S['RangeTarget'];

export type Provider = Account['provider'];
export type Product = NonNullable<Source['product']>;
export type Bucket = UsageSeries['bucket'];
export type TokenComponents = UsageBucket['components'];

export const PRODUCTS_BY_PROVIDER: Record<Provider, readonly Product[]> = {
  gpt: ['chat', 'work', 'codex'],
  claude: ['chat', 'code', 'cowork'],
};
