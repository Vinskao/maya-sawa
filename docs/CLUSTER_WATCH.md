# 叢集異常告警與 CPU 上限（2026-11-17）

**起因：** maya-sawa 裡的 ffmpeg 吃滿唯一的 vCPU，`/healthz` 逾時被殺，worker `10.0.158.183` 的容器執行環境卡住，網站掛約 12 小時沒人發現。恢復步驟見 skill `oke-node-recovery`。

## 1. 告警（`scripts/cluster_watch.py` ＋ `k8s/cluster-watch.yaml`）

CronJob 每 5 分鐘跑一次，**釘在另一台 worker `10.0.159.167`**，所以 `10.0.158.183` 卡住時它還能發訊息（兩台同時壞才會失靈）。腳本只用標準函式庫，以 ConfigMap `cluster-watch-script` 掛進 `python:3.12-alpine`，由 Jenkins 部署時建立。

檢查：
- pod 卡在 `CreateContainerError`、`ContainerCreating`、`ImagePullBackOff`、`CrashLoopBackOff` 等超過 10 分鐘，或 `Pending`／`Terminating` 超過 10 分鐘。
- 節點不是 `Ready`。
- 近 15 分鐘有 `FailedKillPod` 事件（容器執行環境卡住的徵兆）。
- `http://maya-sawa/healthz` 與 `https://tymultiverse.cc/` 連兩次失敗（間隔 5 秒），**且持續 10 分鐘以上**才報。maya-sawa 部署時用 `Recreate` 策略，舊 pod 先關、新 pod 啟動要幾分鐘，這段時間健康檢查本來就會失敗，不是異常（2026-11-18 修正誤報）；失敗起點記在 ConfigMap `cluster-watch-state` 的 `probeFirst`，回應一次就歸零。

通知（Telegram，與其他排程共用 secret `telegram-notify`）：問題清單變化時發一則、同樣的問題每小時提醒一次、恢復時發一則「已恢復」。狀態存在 ConfigMap `cluster-watch-state`，所以不會每 5 分鐘洗版。沒設 Telegram 憑證時只印 log。發送失敗不存狀態，下次再試。

限制：它用的是叢集自己的 CronJob，**兩台 worker 都壞，或整個叢集掛掉就不會有訊息**。要連這種情況也抓，需要叢集外的探針（例如外部服務 ping 網站）。

測試：`tests/infrastructure/test_cluster_watch.py`。手動跑一次：`kubectl create job --from=cronjob/cluster-watch cw-test`，看 `kubectl logs job/cw-test`。

## 2. maya-sawa CPU 上限

`k8s/deployment.yaml` 的 CPU limit 由 `1000m` 降為 `600m`。節點只有約 1 vCPU（可分配約 850m），原本的上限等於整顆，ffmpeg 一吃滿，kubelet 和 containerd 也拿不到 CPU。現在最多佔約 6 成，剩下留給節點與其他 pod。request 維持 `10m`，不影響排程。

代價：maya-sawa 的重工作（影片合成、批次分析）會比較慢。若發現 `/healthz` 仍被節流，可再把 liveness 的 `failureThreshold` 放寬。
