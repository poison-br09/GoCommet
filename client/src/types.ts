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
}

export type Decision =
  | "auto_approve"
  | "flag_for_review"
  | "draft_amendment";

export interface PipelineResult {
  job_id: string;
  status: "processing" | "complete";
  extracted_data: ExtractionOutput | null;
  validation_results: FieldValidation[] | null;
  final_decision: Decision | null;
  decision_reasoning_or_draft: string | null;
}
