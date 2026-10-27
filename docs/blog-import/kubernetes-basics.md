---
title: "kubernetes-basics"
publishDate: "2024-12-13 13:00:00"
img: /tymultiverse/assets/k8s.png
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/12/13
level: advance
category: Kubernetes
tags:
  - Kubernetes
  - Basics
---

# Kubernetes Basics

## Overview

本文件為 Kubernetes 入門指南，介紹其基本元件和架構，幫助初學者理解 Kubernetes 集群的運作原理及核心概念。

## 核心組件

### OS 層級虛擬化

- **C Groups**：由核心管理，用於資源分配。  
- **Libraries 與 Runtimes**：執行容器所必需的基本環境。

### Kubernetes Networking

- **Load Balancer (LB)**：負載均衡器分發流量。  
- **Reverse Proxy**：負責轉發請求。  
- **Domain Registration**：管理對外域名解析。

### 儲存系統

- **Persistent Volume Claim (PVC) / Persistent Volume (PV)**：用於申請和配置動態存儲資源。  
- **Logical Unit Number (LUN)**：主要用於 iSCSI 儲存設備中的區塊識別。

### 集群核心控制元件

- **API Server**：管理集群狀態，搭配 etcd 資料庫。  
- **Scheduler**：決定新的 Pod 部署在哪個 Node 上。  
- **Kubelet**：Node 端運行代理，確保 Pod 狀態。  
- **Static Pod 與 DaemonSet**：管理必須在特定 Node 上運行的服務。

### 其他概念

- **Ingress 與 NodePort**：用於對外暴露服務。  
- **Namespaces**：實現資源的邏輯隔離。  
- **StatefulSet**：管理有狀態的應用。  
- **DNS 與負載均衡**：確保服務發現與流量分發。

