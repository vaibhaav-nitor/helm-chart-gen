# HelmChartGen Crew

CrewAI automation for generating AKS-ready Helm charts from a Git repository scan.

## What It Does

The crew runs this sequence:

1. Clone and scan a Git repository.
2. Analyze application runtime and deployment requirements.
3. Convert app needs into AKS Kubernetes requirements.
4. Generate a Helm chart with Azure Key Vault CSI Driver references.
5. Review the chart for Kubernetes and secret-handling risks.
6. Validate the chart with local Helm tooling.
7. Pause for final human approval.

Secret values are not accepted. Provide Key Vault object references only.

## Local Setup

```powershell
cd D:\Crew-ai\helm_chart_gen
copy .env.example .env
```

Edit `.env` and set at least:

```env
OPENAI_API_KEY=...
MODEL=gpt-4o
```

Install and run:

```powershell
crewai install
crewai run
```

If CrewAI tries to write outside the workspace, set:

```powershell
$env:CREWAI_STORAGE_DIR="D:\Crew-ai\helm_chart_gen\.crewai_storage"
```

## CrewAI Studio Inputs

When deploying or running from CrewAI Studio, provide these kickoff inputs:

```json
{
  "repository_url": "https://github.com/org/app.git",
  "git_ref": "main",
  "app_subdirectory": "",
  "chart_name": "my-app",
  "release_name": "my-app",
  "namespace": "default",
  "image_repository": "myacr.azurecr.io/my-app",
  "image_tag": "1.0.0",
  "container_port": "",
  "ingress_enabled": true,
  "ingress_host": "app.example.com",
  "aks_cluster_name": "aks-dev",
  "azure_tenant_id": "00000000-0000-0000-0000-000000000000",
  "keyvault_name": "my-keyvault",
  "user_assigned_identity_client_id": "00000000-0000-0000-0000-000000000000",
  "secret_mappings_json": "[{\"env\":\"DB_PASSWORD\",\"keyvault_object\":\"db-password\",\"object_type\":\"secret\"}]",
  "config_values_json": "{}",
  "enable_hpa": true,
  "min_replicas": 2,
  "max_replicas": 5
}
```

`secret_mappings_json` must contain references only. Do not include fields such as
`value`, `secret_value`, `password`, `token`, `api_key`, or `apikey`.

## Deploy To CrewAI Studio

Push this project to GitHub, then run:

```powershell
crewai login
crewai deploy create
```

After the first deployment:

```powershell
crewai deploy status
crewai deploy logs
crewai deploy push
```

## Generated Output

Local chart files are written under:

```text
generated_charts/<chart_name>/
```

Temporary cloned repositories are stored under:

```text
.helm_gen_workspace/
```
