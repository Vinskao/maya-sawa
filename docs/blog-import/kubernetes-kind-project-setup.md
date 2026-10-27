---
title: "kubernetes-kind-project-setup"
publishDate: "2024-04-25 13:00:00"
img: /tymultiverse/assets/k8s.png
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/04/25
level: advance
category: Kubernetes
tags:
  - Kubernetes
  - Kind
  - Frontend
  - Backend
  - Database
---

本專案有 3 個必要服務：客戶端服務、伺服器端服務、資料庫服務。

# Kubernetes 與 Helm 指令

這份指令集涵蓋了 Kubernetes 資源的創建、更新、監控和刪除操作，以及使用 Helm 安裝和管理 Kubernetes 應用的例子。

## 安裝和管理 Helm

```bash
# 安裝 Helm
brew install helm

# 查看 Helm 版本
helm version

# 添加 Kubernetes Ingress-Nginx 儲存庫
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx

# 更新 Helm 儲存庫資料
helm repo update

# 安裝 Nginx Ingress Controller，並設定發布服務
helm install nginx-ingress ingress-nginx/ingress-nginx --set controller.publishService.enabled=true

```

## 應用 Kubernetes 配置文件

```bash
# 應用 Persistent Volume 和 Persistent Volume Claim
kubectl apply -f /Users/vinskao/k8s/pv/discord-sql-edge-pv.yaml
kubectl apply -f /Users/vinskao/k8s/pvc/discord-sql-edge-pvc.yaml

# 應用 Kubernetes 服務定義
kubectl apply -f /Users/vinskao/k8s/service/discord-sql-edge-service.yaml
kubectl apply -f /Users/vinskao/k8s/service/discord-frontend-service.yaml
kubectl apply -f /Users/vinskao/k8s/service/discord-backend-service.yaml

# 應用 Kubernetes 開發環境設定
kubectl apply -f /Users/vinskao/k8s/development/discord-sql-edge-development.yaml
kubectl apply -f /Users/vinskao/k8s/development/discord-frontend-development.yaml
kubectl apply -f /Users/vinskao/k8s/development/discord-backend-development.yaml

# 應用 Ingress 設定
kubectl apply -f /Users/vinskao/k8s/ingress/ingress.yaml

# 刪除先前應用的資源
kubectl delete -f /Users/vinskao/k8s/pv/discord-sql-edge-pv.yaml
kubectl delete -f /Users/vinskao/k8s/pvc/discord-sql-edge-pvc.yaml
kubectl delete -f /Users/vinskao/k8s/service/discord-sql-edge-service.yaml
kubectl delete -f /Users/vinskao/k8s/service/discord-frontend-service.yaml
kubectl delete -f /Users/vinskao/k8s/service/discord-backend-service.yaml
kubectl delete -f /Users/vinskao/k8s/development/discord-sql-edge-development.yaml
kubectl delete -f /Users/vinskao/k8s/development/discord-frontend-development.yaml
kubectl delete -f /Users/vinskao/k8s/development/discord-backend-development.yaml
kubectl delete -f /Users/vinskao/k8s/ingress/ingress.yaml
kubectl delete -f /Users/vinskao/k8s/ingress/websocket-ingress.yaml

# 刪除所有資源
kubectl delete all,pv,pvc,sc,ingress --all

# 測試連線性
ping discord-backend.default.svc.cluster.local
ping front-backend.default.svc.cluster.local

# 創建配置映射
kubectl create configmap cors-config --from-literal=allowedOrigins="http://www.localhost,http://api.localhost"

# 查看和監控資源
kubectl get all
kubectl get pods --watch
kubectl logs -l app=discord-backend
kubectl logs -l app=discord-frontend
kubectl logs -l app=sql-edge
kubectl describe pod discord-frontend-8968ff8d9-2742c
kubectl describe pod -l app=sql-edge
kubectl describe pod -l app=discord-backend

# 端口轉發
kubectl port-forward svc/sql-edge-service 1433:1433
kubectl port-forward svc/discord-frontend 8090:8090

# 刪除 Pod 和服務
kubectl delete pod -l app=discord-frontend
kubectl delete pod -l app=discord-backend
kubectl delete pod -l app=sql-edge
kubectl delete deployment sql-edge-deployment
kubectl delete service sql-edge-service
kubectl delete pods -l app=discord-backend
kubectl get pods -l app=discord-frontend
kubectl get pvc
kubectl get pv
kubectl describe pvc
kubectl delete storageclass local-storage
kubectl delete all,pv,pvc,sc --all
kubectl delete deployment discord-backend discord-frontend
kubectl delete service discord-backend discord-frontend


# 查看節點詳情
kubectl get nodes -o wide

## 應用 Ingress 定義
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.1.1/deploy/static/provider/cloud/deploy.yaml

## 構建和推送 Docker 鏡像
docker build -t papakao/discord-frontend:latest ./discord-front-end
docker build -t papakao/discord-backend:latest ./discord-back-end
docker push papakao/discord-frontend:latest
docker push papakao/discord-backend:latest

## 進階設定與故障排除

- **資源管理：** 確保 Persistent Volume、PVC 與 StorageClass 正確配置，防止資源浪費或意外丟失。
- **Helm 功能：** 透過 Helm 除了快速安裝，也能方便進行版本管理和版本回退。
- **網路配置：** 留意 Ingress 與 NodePort 的網路設定，必要時調整防火牆規則。
- **除錯技巧：** 使用 `kubectl describe`、`kubectl logs` 等命令追蹤問題根源，參閱官方文件獲取更多細節。
