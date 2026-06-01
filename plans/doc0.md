你是 ScholarOutboundManager 项目的技术文档作者。请基于下面的项目背景、真实使用案例和安全边界，撰写一套面向用户的 Markdown 文档。

文档目标：

把 ScholarOutboundManager 从“一个命令行工具”写成“一个可以在 VPS 上部署、筛选 Google Scholar 可用节点、暴露本地 SOCKS sidecar 的生产工作流”。

文档必须清晰、可执行、分步骤。每个使用案例都要包含背景、适用场景、前置条件、命令、预期输出、失败判断和下一步处理。

语言使用中文。命令和配置字段保留英文。整体风格要严谨、克制、工程化，不要写成营销文案。

---

# 一、项目定位

ScholarOutboundManager 是一个用于管理 Google Scholar 专用出口节点的工具。

它的核心工作流是：

1. 从订阅链接 fetch 节点。
2. 解析 Clash YAML / URI subscription。
3. 在 VPS 上真实 probe 节点对 Google Scholar 的访问能力。
4. Scholar 可用性分成两层：
   - 首页访问：`https://scholar.google.com/`
   - 检索访问：`https://scholar.google.com/scholar?hl=zh-CN&as_sdt=0%2C5&q=ppr&btnG=`
5. 只有 home/query 都通过，且没有 `google_sorry`、`http_403`、`stage_query_blocked`、`stage_transport_failed` 等失败 marker，才算 `full_access`。
6. 将通过测试的节点写入 sensitive artifact：`state_data/passed_candidates.json`。
7. 从 passed candidates 中选择一个或多个节点。
8. 启动独立的 Xray sidecar，在 localhost 暴露 SOCKS。
9. 生产 Xray/XrayR/x-ui 只需要手工接入这个 localhost SOCKS outbound。
10. ScholarOutboundManager 不修改、不 reload、不 kill 生产 Xray/XrayR/x-ui。

必须强调：

- 本项目不是通用代理客户端。
- 本项目不直接注入生产 Xray/XrayR 配置。
- 本项目采用 sidecar-first 架构。
- 生产接入是手工下游集成，不是自动改生产配置。

---

# 二、安全边界

文档中必须反复强调以下规则：

不要执行：

- `cat config.yaml`
- `cat candidates.json`
- `cat state_data/passed_candidates.json`
- `cat state_data/selected_candidate.json`
- `cat /etc/scholar-outbound-manager/scholar_sidecar_runtime.json`
- `killall xray`
- `pkill xray`
- 自动修改生产 Xray/XrayR/x-ui 配置
- 自动 reload 生产 Xray/XrayR/x-ui
- 提交 `state_data/`、`.runtime/`、`candidates.json`、`passed_candidates.json`

不要在文档输出中暴露：

- subscription URL
- raw URI
- UUID
- public key
- password
- token
- auth
- obfs-password
- server address
- server_name / sni
- runtime config 内容

说明哪些文件是 sensitive：

- `config.yaml`
- `candidates.json`
- `state_data/passed_candidates.json`
- `state_data/selected_candidate.json`
- `/etc/scholar-outbound-manager/scholar_sidecar_runtime.json`

说明哪些输出是 redacted / review-safe：

- `select list`
- `select explain`
- `artifact check`
- `artifact explain-probe`
- `sidecar service-validate`
- `sidecar pool snippets`

---

# 三、文档结构

请生成以下文档章节。

## 1. Overview

解释项目解决什么问题：

- 普通节点能打开网页，不代表能访问 Google Scholar 检索。
- Google Scholar 有两层限制：
  - 首页 403
  - 首页 200，但检索 query 被 Google Sorry / automated query / 403 拦截
- 因此必须对节点做 Scholar 语义级 probe。
- 通过节点后，不应改生产 Xray/XrayR，而是启动独立 sidecar。

## 2. Architecture

用文字和 ASCII 图解释：

```text
subscription
  -> fetch
  -> candidates.json
  -> probe on VPS
  -> probe_summary.json
  -> passed_candidates.json
  -> select / pool plan
  -> sidecar runtime config
  -> systemd-managed Xray sidecar
  -> localhost SOCKS
  -> production Xray/XrayR manual downstream integration
````

解释 sidecar：

```text
systemd
  └── scholar-outbound-sidecar.service
        └── Xray sidecar
              ├── inbound: 127.0.0.1:19080 SOCKS
              └── outbound: selected passed candidate
```

解释 multi-port pool：

```text
one Xray sidecar process
  ├── 127.0.0.1:19080 -> candidate A
  ├── 127.0.0.1:19081 -> candidate B
  ├── 127.0.0.1:19082 -> candidate C
  └── 127.0.0.1:19083 -> candidate D
```

强调：

* 默认不是多个 Xray 进程。
* 多节点出口通过单 Xray、多 SOCKS inbound、多 outbound 实现。
* 多 systemd instance 不是默认路线。

---

# 四、使用案例 1：从订阅重新生成候选节点

场景：

用户在 VPS 上保留了：

* `config.yaml`
* `.runtime/xray/xray`
* `.venv`

需要重新从订阅生成 `candidates.json`。

步骤：

1. 更新仓库：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
git status --short
git pull --ff-only
. .venv/bin/activate
python -m pip install -e .
git rev-parse --short HEAD
git status --short
'
```

2. 检查配置：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager environment
scholar-outbound-manager xray inspect --path .runtime/xray/xray

python - <<'"'"'PY'"'"'
from scholar_outbound_manager.config import load_config

config = load_config("config.yaml")
enabled = [s for s in config.subscriptions if s.enabled]

print(f"subscription_count: {len(config.subscriptions)}")
print(f"enabled_subscription_count: {len(enabled)}")
print(f"probe_allow_network_probe: {config.probe.allow_network_probe}")
print(f"probe_concurrency: {config.probe.concurrency}")
print(f"xray_binary_path: {config.xray.binary_path}")
print(f"routing_fail_closed: {config.routing.fail_closed}")

if not enabled:
    raise SystemExit("No enabled subscription found in config.yaml")
if not config.probe.allow_network_probe:
    raise SystemExit("probe.allow_network_probe must be true")
if not config.routing.fail_closed:
    raise SystemExit("routing.fail_closed must be true")
PY
'
```

3. Fetch：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager fetch \
  --config config.yaml \
  --output candidates.json \
  --allow-network-fetch \
  --user-agent "Clash.Meta"
'
```

4. 安全统计：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

python - <<'"'"'PY'"'"'
from collections import Counter
from scholar_outbound_manager.io import load_candidates

candidates = load_candidates("candidates.json")
protocol_counts = Counter(c.protocol for c in candidates)
supported_protocol_counts = Counter(c.protocol for c in candidates if c.supported)
unsupported_protocol_counts = Counter(c.protocol for c in candidates if not c.supported)

print(f"candidate_count: {len(candidates)}")
print(f"supported_count: {sum(1 for c in candidates if c.supported)}")
print(f"unsupported_count: {sum(1 for c in candidates if not c.supported)}")
print(f"protocol_counts: {dict(sorted(protocol_counts.items()))}")
print(f"supported_protocol_counts: {dict(sorted(supported_protocol_counts.items()))}")
print(f"unsupported_protocol_counts: {dict(sorted(unsupported_protocol_counts.items()))}")
PY
'
```

说明：

* 不要打印 `candidates.json` 内容。
* 如果 `supported_count=0`，不要继续 probe。

---

# 五、使用案例 2：并行 probe 并保留所有通过节点

场景：

用户已经有新的 `candidates.json`，需要在 VPS 上全量测试 Google Scholar 可用性。

命令：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

mkdir -p state_data

scholar-outbound-manager probe \
  --config config.yaml \
  --candidates candidates.json \
  --summary-output state_data/probe_summary.json \
  --passed-candidates-output state_data/passed_candidates.json \
  --parallel 4 \
  --keep-all-passed \
  --query ppr \
  --xray-test-timeout 10 \
  --startup-timeout 5 \
  --request-timeout 15 \
  --allow-network-probe
'
```

解释：

* `--parallel 4`：并行测试 4 个候选。
* `--keep-all-passed`：保留所有通过节点，不只保留第一个。
* 返回码：

  * `0`：至少一个节点通过。
  * `2`：测试完成，但没有节点通过。
  * `1`：配置、runtime 或写入失败。

写出：

* `state_data/probe_summary.json`：redacted summary。
* `state_data/passed_candidates.json`：sensitive artifact，含真实节点字段，不可提交。

---

# 六、使用案例 3：检查 artifact 是否同源

场景：

用户重新 fetch/probe 多次后，可能混用了旧的 `probe_summary.json` 或 `passed_candidates.json`。需要检查三个 artifact 是否来自同一轮。

命令：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager artifact check \
  --candidates candidates.json \
  --probe-summary state_data/probe_summary.json \
  --passed-candidates state_data/passed_candidates.json
'
```

解释：

* `candidate_id` 属于某一轮 artifact，不等于当前 `candidates.json` 的 index。
* 如果 artifact mismatch，不要继续 selection。
* 正确处理是重新 fetch + probe。

---

# 七、使用案例 4：查看 passed candidates 并人工选择节点

场景：

用户想知道哪些节点通过 Scholar 测试，并手工选择 US/JP/HK 等节点。

查看列表：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager select list \
  --candidates state_data/passed_candidates.json
'
```

说明输出字段：

* `index`
* `candidate_id`
* `protocol`
* `label`
* `region`
* `passed`
* `stage`
* `home`
* `query`
* `markers`

说明：

* `label` 是 redacted node label。
* `region_hint` 来自 label heuristic，不是 GeoIP。
* 手工选择应使用 `candidate_id`，不要用当前 `candidates.json` 的 index 猜。

选择节点：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager select choose \
  --candidates state_data/passed_candidates.json \
  --candidate-id "<TARGET_CANDIDATE_ID>" \
  --output state_data/selected_candidate.json
'
```

自动优先 US region hint：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager select choose \
  --candidates state_data/passed_candidates.json \
  --strategy auto \
  --preferred-region-hint US \
  --output state_data/selected_candidate.json
'
```

说明：

* region hint 只在 passed pool 内选择。
* 它不会把未通过 Scholar 的 US 节点提升为可部署节点。

---

# 八、使用案例 5：解释为什么某个地区节点没有进入 passed pool

场景：

订阅中存在 US 节点，但 `select list --passed_candidates` 里没有 US。

首先看原始 candidates：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager select list \
  --candidates candidates.json | grep -Ei "US|USA|United|America|LA|Los Angeles|美国|洛杉矶" || true
'
```

然后看 probe 结果：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager artifact explain-probe \
  --probe-summary state_data/probe_summary.json \
  --label-regex "US|USA|United|America|LA|Los Angeles|美国|洛杉矶"
'
```

解释：

* 如果 query 是 403 或 marker 有 `google_sorry` / `stage_query_blocked`，说明节点地理上接近，但 Scholar 检索不可用。
* Scholar 可用性优先于地理距离。
* 未通过的节点不应部署到 sidecar。

---

# 九、使用案例 6：部署单节点 systemd sidecar

场景：

用户已经生成 `selected_candidate.json`，希望让 sidecar 使用该节点。

Stage runtime config，不覆盖 Xray binary：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar service-stage \
  --config config.yaml \
  --selected-candidate state_data/selected_candidate.json \
  --listen-host 127.0.0.1 \
  --listen-port 19080 \
  --skip-xray-binary-copy
'
```

如果目标 binary 不存在，首次恢复时复制一次：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar service-stage \
  --config config.yaml \
  --selected-candidate state_data/selected_candidate.json \
  --listen-host 127.0.0.1 \
  --listen-port 19080 \
  --source-xray-binary .runtime/xray/xray
'
```

安装 systemd service：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar service-install \
  --unit-name scholar-outbound-sidecar.service \
  --service-user scholar-sidecar \
  --service-group scholar-sidecar
'
```

重启并验证：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar service-restart \
  --unit-name scholar-outbound-sidecar.service

scholar-outbound-manager sidecar service-validate \
  --unit-name scholar-outbound-sidecar.service \
  --listen-host 127.0.0.1 \
  --listen-port 19080 \
  --query ppr \
  --request-timeout 15
'
```

预期：

```text
service_active: true
service_enabled: true
socks_tcp_connect: true
scholar_stage: full_access
scholar_passed: true
home_status: 200
query_status: 200
```

---

# 十、使用案例 7：切换优选节点

场景：

当前 sidecar 已经运行，但用户想切换到另一个 passed candidate。

步骤：

1. 查看 passed candidates。
2. 选择新 candidate。
3. 重新 stage runtime config。
4. restart service。
5. validate。

命令：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager select choose \
  --candidates state_data/passed_candidates.json \
  --candidate-id "<TARGET_CANDIDATE_ID>" \
  --output state_data/selected_candidate.json

scholar-outbound-manager sidecar service-stage \
  --config config.yaml \
  --selected-candidate state_data/selected_candidate.json \
  --listen-host 127.0.0.1 \
  --listen-port 19080 \
  --skip-xray-binary-copy

scholar-outbound-manager sidecar service-restart \
  --unit-name scholar-outbound-sidecar.service

scholar-outbound-manager sidecar service-validate \
  --unit-name scholar-outbound-sidecar.service \
  --listen-host 127.0.0.1 \
  --listen-port 19080 \
  --query ppr \
  --request-timeout 15
'
```

解释：

* 切换节点只需要重写 runtime config。
* 不应覆盖正在运行的 Xray binary。
* `--skip-xray-binary-copy` 是推荐方式。

---

# 十一、使用案例 8：多节点出口 pool

场景：

用户希望一个 sidecar Xray 同时暴露多个本地 SOCKS 端口，每个端口对应一个 passed candidate。

自动取前 4 个 passed 节点：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar pool plan \
  --candidates state_data/passed_candidates.json \
  --max-count 4 \
  --base-port 19180 \
  --output state_data/sidecar_pool_plan.json

scholar-outbound-manager sidecar pool check-ports \
  --plan state_data/sidecar_pool_plan.json
'
```

手工指定多个 candidate：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar pool plan \
  --candidates state_data/passed_candidates.json \
  --candidate-id "<CANDIDATE_ID_1>" \
  --candidate-id "<CANDIDATE_ID_2>" \
  --candidate-id "<CANDIDATE_ID_3>" \
  --base-port 19180 \
  --output state_data/sidecar_pool_plan.json
'
```

Stage pool config：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar pool stage \
  --config config.yaml \
  --candidates state_data/passed_candidates.json \
  --plan state_data/sidecar_pool_plan.json \
  --skip-xray-binary-copy
'
```

Restart and validate：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar service-restart \
  --unit-name scholar-outbound-sidecar.service

scholar-outbound-manager sidecar pool validate \
  --plan state_data/sidecar_pool_plan.json \
  --query ppr \
  --request-timeout 15
'
```

输出 snippets：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar pool snippets \
  --plan state_data/sidecar_pool_plan.json
'
```

说明：

* pool 使用单 Xray，多 SOCKS inbound，多 outbound。
* 不启动多个 Xray 实例。
* 如果 `19080` 已被当前 sidecar 占用，可以用 `19180` 测试。
* pool snippets 只供生产 Xray/XrayR 手工接入，不自动写配置。

---

# 十二、使用案例 9：Hysteria2 支持与排障

解释：

Xray 中 Hysteria2 通过 `protocol: hysteria` 表达，配置中使用 version 2。项目已经支持将 conservative `hysteria2` candidate 映射为 Xray hysteria outbound。

已支持：

* `server`
* `port`
* `password/auth`
* `sni/servername -> tlsSettings.serverName`
* `skip-cert-verify -> tlsSettings.allowInsecure`

仍 fail-closed：

* `obfs`
* `obfs-password`
* `alpn`，如果当前未明确映射

排查 Hysteria2：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager artifact explain-probe \
  --probe-summary state_data/probe_summary.json \
  --protocol hysteria2
'
```

只看 SSL EOF：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager artifact explain-probe \
  --probe-summary state_data/probe_summary.json \
  --protocol hysteria2 \
  --error-category ssl_eof
'
```

说明：

* `ssl_eof` 是 transport-layer failure，不是 Scholar 403。
* 如果 Hysteria2 大量 `stage_transport_failed`，不要部署这些节点。
* 只有进入 `passed_candidates.json` 的 Hysteria2 才能作为生产候选。

---

# 十三、使用案例 10：生产 Xray/XrayR 手工接入

单节点 sidecar snippet：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar service-snippet \
  --listen-host 127.0.0.1 \
  --listen-port 19080 \
  --tag scholar-sidecar-socks-out
'
```

多节点 pool snippets：

```bash
ssh my_vps 'set -e
cd /root/ScholarOutboundManager-live/ScholarOutboundManager
. .venv/bin/activate

scholar-outbound-manager sidecar pool snippets \
  --plan state_data/sidecar_pool_plan.json
'
```

强调：

* 这些 snippets 不会自动写入生产配置。
* 用户应手工把它们接入自己的生产 Xray/XrayR。
* ScholarOutboundManager 不负责 reload 生产服务。

---

# 十四、Troubleshooting

必须包含以下故障解释。

## enabled_subscription_count = 0

原因：

`config.yaml` 中没有启用的 subscription。

处理：

* 修改 ignored 的 `config.yaml`。
* 确保至少一个 subscription `enabled: true`。
* 不要把 config.yaml 提交。

## select explain 没有 US 节点

原因：

`select explain` 只看 `passed_candidates.json`。如果 US 节点没有进入 passed pool，就不会出现。

处理：

* 用 `select list --candidates candidates.json` 看原始节点。
* 用 `artifact explain-probe` 看 US 节点是否 query blocked。
* 不要强行部署未 passed 节点。

## candidate_id 选出和预期不同的节点

原因：

artifact 不同源。`candidate_id` 属于某一轮 fetch/probe，不等于当前 candidates index。

处理：

* 运行 `artifact check`。
* 如果 mismatch，重新 fetch + probe。

## Text file busy

原因：

sidecar service 正在运行 `/opt/scholar-outbound-manager/xray/xray`，旧版本 service-stage 试图覆盖 running binary。

处理：

* 使用 `--skip-xray-binary-copy`。
* 只更新 runtime config。
* 如果需要升级 binary，先停服务，再做显式升级。

## google_sorry / stage_query_blocked

含义：

首页可能 200，但 Scholar query 被 Google 拦截。

处理：

* 该节点不能进入生产 sidecar。
* 选择其它 passed candidate。

## ssl_eof / stage_transport_failed

含义：

TLS/传输层失败，不是 Scholar 语义封锁。

处理：

* 按 protocol 过滤。
* 如果集中在 hysteria2，检查 Hysteria2 字段映射。
* 不要部署未 passed 节点。

---

# 十五、最终文档风格要求

文档必须：

* 以真实 VPS 使用流程为主线。
* 每个步骤给出完整命令。
* 每个命令说明是否安全、是否联网、是否写 sensitive artifact。
* 明确哪些命令不会修改生产 Xray/XrayR。
* 明确哪些文件不可提交。
* 所有示例里的 candidate_id 用 placeholder 或 fake ID。
* 不出现真实订阅 URL、真实 UUID、真实 public key、真实 server address。
* 不把 legacy generate 作为主流程。
* 如果提到 generate，只说明它是 legacy/offline fragment export。

请输出完整 Markdown 文档草案。

