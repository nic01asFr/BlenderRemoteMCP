{{- define "blender-remote-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "blender-remote-mcp.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "blender-remote-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: onyxia
app: blender-remote-mcp
{{- end -}}

{{- define "blender-remote-mcp.selectorLabels" -}}
app: blender-remote-mcp
app.kubernetes.io/name: {{ include "blender-remote-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
