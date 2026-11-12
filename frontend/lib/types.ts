export type User = { id: number; email: string; full_name: string };

export type CrawlSettings = {
  max_urls: number;
  max_depth: number;
  concurrency: number;
  delay_ms: number;
  max_retries: number;
  respect_robots: boolean;
  use_sitemaps: boolean;
  follow_links: boolean;
  follow_canonicals: boolean;
  include_subdomains: boolean;
  allowed_hosts: string[];
  render_js: "never" | "auto" | "always";
  exclude_patterns: string[];
  include_patterns: string[];
  strip_query_params: string[];
  ignore_query_strings: boolean;
};

export type AISettings = {
  provider: "anthropic" | "openai" | null;
  model: string | null;
  effort: "low" | "medium" | "high" | "xhigh" | "max";
  max_attempts: number;
  concurrency: number;
  min_words: number;
  include_non_indexable: boolean;
};

export type Project = {
  id: number;
  name: string;
  domain: string;
  base_url: string;
  primary_market: string;
  language: string;
  target_country: string;
  target_audience: string;
  business_category: string;
  crawl_settings: Partial<CrawlSettings>;
  ai_settings: Partial<AISettings>;
  created_at: string;
  updated_at: string;
};

export type Issue = {
  code?: string;
  field: string;
  name: string;
  severity: "Critical" | "High" | "Medium" | "Low";
  explanation?: string;
  recommendation?: string;
  source?: string;
  blocking?: boolean;
};

export type PageRow = {
  id: number;
  s_no: number;
  url: string;
  page_type: string;
  is_indexable: boolean | null;
  primary_keyword: string;
  existing_title: string | null;
  existing_title_len: number;
  proposed_title: string | null;
  proposed_title_len: number | null;
  existing_description: string | null;
  existing_description_len: number;
  proposed_description: string | null;
  proposed_description_len: number | null;
  existing_score: number | null;
  proposed_score: number | null;
  issues: Issue[];
  issue_count: number;
  critical_count: number;
  proposal_source: string | null;
  validation_status: string;
  title_status: string;
  description_status: string;
  approval_status: string;
};

export type CrawlJob = {
  id: number;
  project_id: number;
  status: string;
  settings: Partial<CrawlSettings>;
  stats: { discovered?: number; crawled?: number; failed?: number; queued?: number; by_status?: Record<string, number> };
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

export type AIJob = {
  id: number;
  kind: string;
  status: string;
  params: Record<string, unknown>;
  total: number;
  processed: number;
  failed: number;
  error: string | null;
  log: { t: string; m: string }[];
  created_at: string;
  finished_at: string | null;
};

export type Guidelines = {
  id: number;
  version: number;
  is_active: boolean;
  brand_context: Record<string, string>;
  seo_guidelines: Record<string, unknown> & { page_type_rules?: Record<string, string> };
  guardrails: Record<string, unknown> & { formatting?: Record<string, boolean> };
  keywords: { keyword: string; priority: string; applies_to: string }[];
  custom_instructions: string;
  change_note: string;
  created_at: string;
};
