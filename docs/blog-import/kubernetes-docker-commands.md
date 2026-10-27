---
title: "kubernetes-docker-commands"
publishDate: "2024-05-06 13:00:00"
img: /tymultiverse/assets/k8s.png
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/05/06
level: advance
category: Kubernetes
tags:
  - Kubernetes
  - Docker
  - Commands
---

# Docker 與 Kubernetes 指令大全

Docker 和 Kubernetes 是現代軟件開發中非常關鍵的容器化和集群管理技術。Docker 用於建立和管理容器，而 Kubernetes（簡稱 k8s）則用於自動部署、擴展和管理容器化應用的集群。下面是兩者的指令大全，並說明其功能和差異。

## Docker 指令

### 基本管理

- `docker run`: 啟動一個新容器
  - `docker run -d`: 在後台運行容器
  - `docker run -p`: 映射端口
  - `docker run --name`: 為容器指定名稱
- `docker stop [container]`: 停止運行中的容器
- `docker start [container]`: 啟動已停止的容器
- `docker restart [container]`: 重啟容器
- `docker rm [container]`: 刪除容器
- `docker ps`: 列出容器
  - `docker ps -a`: 列出所有容器，包括未運行的
- `docker logs [container]`: 查看容器的日誌

- `run`：從一個映像檔創建並運行一個新的容器
- `exec`：在運行中的容器執行命令
- `ps`：列出容器
- `build`：從 Dockerfile 建立映像檔
- `pull`：從登錄處下載映像檔
- `push`：上傳映像檔到登錄處
- `images`：列出映像檔
- `login`：登錄到登錄處
- `logout`：從登錄處登出
- `search`：搜索 Docker Hub 上的映像檔
- `version`：顯示 Docker 版本資訊
- `info`：顯示系統廣泛的資訊

### Image管理

- `docker images`: 列出本地存儲的所有鏡像
- `docker pull [image]`: 從遠端倉庫拉取鏡像
- `docker push [image]`: 將本地鏡像推送到遠端倉庫
- `docker build -t [tag]`: 依據 Dockerfile 構建鏡像
- `docker rmi [image]`: 刪除鏡像

### 網絡和卷管理

- `docker network create [options]`: 創建一個新的網絡
- `docker volume create [options]`: 創建一個新的卷

### 管理命令：

- `builder`：管理建造
- `compose*`：Docker Compose (Docker Inc., v2.19.1)
- `container`：管理容器
- `context`：管理上下文
- `image`：管理映像檔
- `network`：管理網絡
- `plugin`：管理插件
- `system`：管理 Docker
- `volume`：管理卷

## Kubernetes 指令

### 基本操作

- `kubectl get nodes`: 查看集群中的節點
- `kubectl get pods`: 查看所有 pod
- `kubectl describe pod [pod_name]`: 查看特定 pod 的詳細信息
- `kubectl apply -f [file.yaml]`: 依據 YAML 文件創建或修改資源
- `kubectl delete -f [file.yaml]`: 刪除 YAML 文件定義的資源

### 全域選項：

- `--config string`：客戶端配置檔案的位置 (預設 "/Users/vinskao/.docker")
- `-c, --context string`：使用的上下文名稱 (覆蓋 DOCKER_HOST 環境變量)
- `-D, --debug`：啟用調試模式
- `-H, --host list`：連接到守護進程的 socket
- `-l, --log-level string`：設置日誌級別 (預設 "info")
- `--tls`：使用 TLS；由 --tlsverify 隱含
- `--tlscacert string`：僅信任由此 CA 簽名的證書 (預設 "/Users/vinskao/.docker/ca.pem")
- `--tlscert string`：TLS 證書檔案路徑 (預設 "/Users/vinskao/.docker/cert.pem")
- `--tlskey string`：TLS 金鑰檔案路徑 (預設 "/Users/vinskao/.docker/key.pem")
- `--tlsverify`：使用 TLS 並驗證遠端
- `-v, --version`：列印版本資訊並退出
  """

### 資源管理

- `kubectl create deployment [name] --image=[image]`: 創建一個新的 Deployment
- `kubectl scale deployment [name] --replicas=[number]`: 調整 Deployment 的副本數量
- `kubectl expose deployment [name] --port=[port] --type=[type]`: 將 Deployment 暴露成一個新的服務

### 進階管理

- `kubectl rollout status deployment/[name]`: 查看 Deployment 的更新狀態
- `kubectl set image deployment/[name] [container]=[new_image]`: 更新容器的鏡像

## Kubectl 命令使用

kubectl controls the Kubernetes cluster manager.

Find more information at: https://kubernetes.io/docs/reference/kubectl/

### 基本命令（初學者）：

- `create`：從文件或標準輸入創建資源
- `expose`：將複制控制器、服務、部署或 Pod 暴露為新的 Kubernetes 服務
- `run`：在集群上運行特定映像
- `set`：在對象上設置特定功能

### 基本命令（中級）：

- `explain`：獲得資源的文檔
- `get`：顯示一個或多個資源
- `edit`：在伺服器上編輯資源
- `delete`：通過文件名、標準輸入、資源和名稱或通過資源和標籤選擇器刪除資源

## 功能差異

### 應用範圍

- **Docker** 是主要用於單機的容器管理工具，能夠在單個系統上有效地管理容器。
- **Kubernetes** 則是為了在多節點的集群環境中管理容器而設計，專門用於大規模的容器部署和管理。

### 管理層面

- **Docker** 提供了容器的基本生命週期管理功能，例如創建、運行、停止和刪除容器。
- **Kubernetes** 提供更全面的管理功能，包括自動擴展、負載均衡、自我修復和服務發現等。
