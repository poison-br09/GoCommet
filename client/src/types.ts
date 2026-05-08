export interface FieldValue {
  value: string | null;
  confidence: number | null;
}

export interface LineItem {
  description: string | null;
  quantity: string | null;
  hs_code: string | null;
  origin: string | null;
  incoterms: string | null;
  unit_price: string | null;
  currency: string | null;
  net_weight: string | null;
  gross_weight: string | null;
}

export interface ExtractionOutput {
  document_name?: string;
  path?: string;
  consignee_name: FieldValue;
  hs_code: FieldValue;
  port_of_loading: FieldValue;
  port_of_discharge: FieldValue;
  incoterms: FieldValue;
  description_of_goods: FieldValue;
  gross_weight: FieldValue;
  invoice_number: FieldValue;
  global_confidence_score: number | null;
  line_items: LineItem[] | null;
}

export interface FieldValidation {
  field_name: string;
  status: "match" | "mismatch" | "uncertain";
  found_value: string | null;
  expected_value: string | null;
  document_name?: string | null;
  source_snippet?: string | null;
  source_doc?: string | null;
  source_doc_expected?: string | null;
  confidence?: number | null;
  validation_type?: "cross_document" | "customer_rules" | string;
  resolution_action?: string | null;
  resolved_by?: string | null;
}

export type Decision =
  | "auto_approve"
  | "flag_for_review"
  | "draft_amendment";

export interface IncomingEmail {
  sender: string;
  sender_name?: string;
  subject: string;
  attachment_paths: string[];
  preview?: string;
}

export interface PipelineResult {
  job_id: string;
  thread_id: string;
  received_at?: string;
  status: "processing" | "pending_review" | "sent" | "complete" | "failed";
  incoming_email: IncomingEmail | null;
  extracted_data: ExtractionOutput[] | ExtractionOutput | Record<string, FieldValue> | null;
  validation_results: FieldValidation[] | null;
  final_decision: Decision | null;
  decision_reasoning_or_draft: string | null;
  human_review_status: string | null;
  edited_email_text: string | null;
  mock_send_result: {
    to?: string;
    subject?: string;
    body?: string;
    status?: string;
    delivery?: string;
    sent_at?: string;
    message_id?: string;
  } | null;
  error_message: string | null;
  progress?: { stage: string; pct: number };
}

export interface PendingReviewItem {
  thread_id: string;
  updated_at: string;
  received_at?: string;
  status: PipelineResult["status"] | null;
  incoming_email: IncomingEmail | null;
  final_decision: Decision | string | null;
  decision_reasoning_or_draft: string | null;
  validation_results: FieldValidation[] | null;
  error_message: string | null;
}
