// This command only renders prompts; it has no inference or HTTP client path.
package main

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"

	"github.com/ollama/ollama/api"
	"github.com/ollama/ollama/template"
)

type templateSource string

const goTemplate templateSource = "go_template"

type renderInput struct {
	Key            string          `json:"key"`
	Wire           json.RawMessage `json:"wire"`
	Template       string          `json:"template"`
	TemplateSource templateSource  `json:"template_source"`
}

type renderOutput struct {
	Key            string `json:"key"`
	WireSha256     string `json:"wire_sha256"`
	TemplateSha256 string `json:"template_sha256"`
	PromptSha256   string `json:"prompt_sha256"`
	Prompt         string `json:"prompt"`
	Renderer       string `json:"renderer"`
}

func digest(content []byte) string {
	checksum := sha256.Sum256(content)
	return hex.EncodeToString(checksum[:])
}

func render(input renderInput) (renderOutput, error) {
	if input.TemplateSource != goTemplate {
		return renderOutput{}, fmt.Errorf("unsupported renderer source: %s", input.TemplateSource)
	}
	var request api.ChatRequest
	if err := json.Unmarshal(input.Wire, &request); err != nil {
		return renderOutput{}, err
	}
	if request.Think == nil || request.Think.Bool() {
		return renderOutput{}, fmt.Errorf("this verification requires explicit think=false")
	}
	for _, message := range request.Messages {
		if len(message.Images) != 0 {
			return renderOutput{}, fmt.Errorf("image inputs require a different tokenizer accounting path")
		}
	}
	parsed, err := template.Parse(input.Template)
	if err != nil {
		return renderOutput{}, err
	}
	var prompt bytes.Buffer
	if err := parsed.Execute(&prompt, template.Values{
		Messages:   request.Messages,
		Tools:      request.Tools,
		Think:      request.Think.Bool(),
		ThinkLevel: request.Think.String(),
		IsThinkSet: true,
	}); err != nil {
		return renderOutput{}, err
	}
	return renderOutput{
		Key:            input.Key,
		WireSha256:     digest(input.Wire),
		TemplateSha256: digest([]byte(input.Template)),
		PromptSha256:   digest(prompt.Bytes()),
		Prompt:         prompt.String(),
		Renderer:       "github.com/ollama/ollama/template@v0.40.13",
	}, nil
}

func run() error {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 64*1024), 16*1024*1024)
	output := json.NewEncoder(os.Stdout)
	for scanner.Scan() {
		var input renderInput
		if err := json.Unmarshal(scanner.Bytes(), &input); err != nil {
			return err
		}
		rendered, err := render(input)
		if err != nil {
			return err
		}
		if err := output.Encode(rendered); err != nil {
			return err
		}
	}
	return scanner.Err()
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
