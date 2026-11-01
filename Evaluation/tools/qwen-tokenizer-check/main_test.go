package main

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func recordedTemplate(t *testing.T) string {
	t.Helper()
	content, err := os.ReadFile("../../runs/contextual/model-evaluation-preparation-v1/20261101-01/qwen-show.json")
	if err != nil {
		t.Fatal(err)
	}
	var metadata struct {
		Template string `json:"template"`
	}
	if err := json.Unmarshal(content, &metadata); err != nil {
		t.Fatal(err)
	}
	return metadata.Template
}

func TestPreservesFullNegativeConditionsAndWireIdentity(t *testing.T) {
	wire := json.RawMessage(`{"model":"qwen3:8b","think":false,"messages":[{"role":"system","content":"원문·부정·조건 보존"},{"role":"user","content":"과거 공사로 통행할 수 없었다. 계단 조건."}]}`)
	result, err := render(renderInput{Key: "offline-regression", Wire: wire, Template: recordedTemplate(t), TemplateSource: goTemplate})
	if err != nil {
		t.Fatal(err)
	}
	if result.WireSha256 != digest(wire) {
		t.Fatal("wire identity changed")
	}
	if !strings.Contains(result.Prompt, "과거 공사로 통행할 수 없었다. 계단 조건.") {
		t.Fatal("original content missing")
	}
	if !strings.HasSuffix(result.Prompt, "<|im_start|>assistant\n<think>\n\n</think>\n\n") {
		t.Fatal("wrong non-thinking generation suffix")
	}
}

func TestUsesTheSameMessageCollationAsOllama(t *testing.T) {
	wire := json.RawMessage(`{"think":false,"messages":[{"role":"user","content":"first"},{"role":"user","content":"second"},{"role":"tool","content":"negative"},{"role":"tool","content":"condition"}]}`)
	result, err := render(renderInput{Wire: wire, Template: recordedTemplate(t), TemplateSource: goTemplate})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(result.Prompt, "first\n\nsecond") {
		t.Fatal("consecutive users not collated")
	}
	if strings.Count(result.Prompt, "<tool_response>") != 2 {
		t.Fatal("tool messages were merged or dropped")
	}
}

func TestUnsupportedRenderingPathsFailExplicitly(t *testing.T) {
	checks := []renderInput{
		{Wire: json.RawMessage(`{"think":false}`), TemplateSource: "renderer_parser"},
		{Wire: json.RawMessage(`{"think":true}`), TemplateSource: goTemplate},
		{Wire: json.RawMessage(`{"messages":[]}`), TemplateSource: goTemplate},
		{Wire: json.RawMessage(`{"think":false,"messages":[{"role":"user","images":["AA=="]}]}`), TemplateSource: goTemplate},
	}
	for _, input := range checks {
		input.Template = recordedTemplate(t)
		if _, err := render(input); err == nil {
			t.Fatal("unsupported path accepted")
		}
	}
}
