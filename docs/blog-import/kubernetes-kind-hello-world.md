---
title: "kubernetes-kind-hello-world"
publishDate: "2024-04-25 12:00:00"
img: /tymultiverse/assets/k8s.png
img_alt: A bright pink sheet of paper used to wrap flowers curves in front of rich blue background
description: |
  2024/04/25
level: advance
category: Kubernetes
tags:
  - Kubernetes
  - Kind
  - Spring Boot
  - Hello World
---

建立一個 Spring Boot Hello World 專案並放上 kind。需要以下四個檔案：

- kind-config.yaml：這個檔案用來設定本地 Kubernetes 叢集。 它定義了叢集的結構，包括節點數量、每個節點的角色（例如控制平面節點或工作節點），以及任何特殊的網路或儲存配置。

- Dockerfile：這是用來建置應用程式 Docker 映像的檔案。 它包含了從基礎映像安裝依賴、複製應用程式程式碼、建置應用程式等所有步驟。

- deployment.yaml：這個檔案定義了在 Kubernetes 上部署您的應用程式的方式。 它指定了應用程式使用的 Docker 映像，需要建立多少副本（Pods），以及 Pod 的其他配置，如環境變數、儲存磁碟區等。

- service.yaml：這個檔案定義了存取應用程式的方式。 在 Kubernetes 中，Service 資源用來暴露應用，可以設定為內部存取（ClusterIP）、外部存取（NodePort、LoadBalancer）等。 這使得其他服務或使用者能夠透過固定的地址存取您的應用程式。

需要安裝項目：

1. docker desktop
2. kind

安裝 Kind 後，kubectl 也會自動安裝，因為 kubectl 是 Kubernetes 的命令列工具，用來與 Kubernetes 叢集互動。 安裝 kubectl 讓你可以管理和操作你透過 Kind 建立的本機 Kubernetes 叢集。

## 刪除 K8s 所有服務

```bash
kind delete clusters --all
```

在測試環境中暫停 Kind 創建的容器：

```bash
docker stop $(docker ps -q --filter "name=kind")
docker stop $(docker ps -q --filter "name=k8s")
```

删除所有部署：

```bash
kubectl delete deployments --all
```

删除所有服务：

```bash
kubectl delete deployments --all
```

删除所有 Pods（如果有必要）：

```bash
kubectl delete pods --all --force --grace-period=0
```

删除镜像

```bash
docker rmi --force registry.k8s.io/kube-apiserver:v1.27.2
docker rmi --force registry.k8s.io/kube-controller-manager:v1.27.2
docker rmi --force registry.k8s.io/kube-scheduler:v1.27.2
docker rmi --force registry.k8s.io/kube-proxy:v1.27.2
```

强制停止所有容器

```bash
# 强制停止所有相关容器
docker ps -a -q --filter "name=k8s" | xargs -I {} docker stop {}

# 删除所有相关容器
docker ps -a -q --filter "name=k8s" | xargs -I {} docker rm {}
```

```java
package com.example.demo;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;

@SpringBootApplication
public class DemoApplication {

	public static void main(String[] args) {
		SpringApplication.run(DemoApplication.class, args);
		printHello();
	}

  @GetMapping("/")
	public static void printHello() {
		System.out.println("Hello, World!");
	}
}
```

## Dockerfile 撰寫

```dockerfile
# 使用包含 Maven 的 Java 基礎映像
FROM maven:3.8.4-openjdk-11-slim as build

# 複製專案文件到容器中
COPY . /app

# 設定工作目錄
WORKDIR /app

# 使用 Maven 來構建專案
RUN mvn clean package

# 運行階段使用更輕量級的 Java 基礎映像
FROM openjdk:11-jre-slim

# 從構建階段複製構建好的應用
COPY --from=build /app/target/demo-0.0.1-SNAPSHOT.jar /app/demo.jar

# 啟動應用
CMD ["java", "-jar", "/app/demo.jar"]
```

## kind-config.yaml 撰寫

##### control-plane

控制群集負責叢集的全域管理，包括以下幾個關鍵元件：

- Kube-API Server：Kubernetes API 的服務接口，所有操作和通訊都需要透過它來進行。在叢集中運行各種操作。
- etcd：一個輕量級、高可靠的關鍵值存儲，用於保存所有群集數據，是 Kubernetes 的主要數據存儲。
- Kube-Scheduler：負責調度 Pod 到適合的工作節點上。日期等）進行決策。
- Kube-Controller-Manager：執行控制器程序。

##### worker（工作節點）

工作節點負責運行應用容器和相關的工作負載。

- Kubelet：在每個節點上執行的代理，確保容器都在運行於 Pod 中。
- Kube-Proxy：在每個節點上運行的網路代理，負責 Kubernetes 服務的網路通訊。
- Container Runtime：容器運作時，如 Docker、containerd 等，負責容器的運作。

每個工作節點都執行以下元件：

- Kubelet：一個。
- Kube-Proxy：一個。
- 容器 Runtime：一個（如 Docker 或 containerd）。

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 30000
        hostPort: 30000
        listenAddress: "0.0.0.0"
        protocol: TCP
  - role: worker
  - role: worker
```

## deployment.yaml 撰寫

```yaml
apiVersion: apps/v1
# 指定使用的 Kubernetes API 版本，apps/v1 是常用於部署的 API 版本。

kind: Deployment
# 指定資源類型，Deployment 是 Kubernetes 中用於管理應用程式執行個體的一種方式，支援宣告式更新。

metadata:
   name: hello-kubernetes
   # 元資料部分定義了資源的名稱等訊息，這裡定義 Deployment 的名字為 hello-kubernetes。

spec:
   # spec 定義了部署的詳細規格。

   replicas: 3
   # replicas 指定希望運行的 Pod 副本數量，這裡設定為 3，表示 Kubernetes 將嘗試保持始終有三個 Pod 實例在運行。

   selector:
     matchLabels:
       app: hello-kubernetes
     # selector 用於選擇與此 Deployment 相關聯的 Pod，matchLabels 是選擇標籤，這裡使用 app: hello-kubernetes 標籤選擇 Pod。

   template:
     # template 定義了 Pod 的模板。

     metadata:
       labels:
         app: hello-kubernetes
       # 在範本的元資料中定義了 Pod 的標籤，這些標籤用於透過上面定義的 selector 來關聯 Pod 和 Deployment。

     spec:
       # 在範本規格中定義了 Pod 的內容。

       containers:
         - name: hello-kubernetes
           # 容器的名稱，每個容器在一個 Pod 中需要有一個唯一的名稱。
          image: papakao/hello-kubernetes:1.0 # 更改為你的username/映像名稱
          ports:
            - containerPort: 8080
            # 容器需要暴露的端口，這裡暴露 8080 端口供外部訪問。
```

## service.yaml 撰寫

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nodeport-demo
spec:
  type: NodePort
  ports:
    - port: 80
      targetPort: 8080
      nodePort: 30000
  selector:
    app: hello-kubernetes
```

## 叢集

叢集（由 Kind 管理）提供了一個本地 Kubernetes 環境，可以模擬生產環境的部署。

### 創建叢集

```bash
kind create cluster --config kind-config.yaml
```

## 鏡像

#### 建構鏡像

```bash
docker build -t papakao/hello-kubernetes:1.0 .
```

#### 推送鏡像至 docker hub

```bash
docker login
docker push papakao/hello-kubernetes:1.0
```

## 部署

#### 套用 deployment.yaml

部署管理 Pod 的生命週期，如部署、更新和擴充。

```bash
kubectl apply -f deployment.yaml
```

#### 套用 service.yaml

服務（Kubernetes Service）確保應用程式元件可以一致且可靠地訪問，無論背後有多少 Pod 在支援。

Pod 是部署的基本單元，每個 Pod 包含了應用程式的一個容器實例。

```bash
kubectl apply -f service.yaml
```

## 驗證部署

#### 查看 Pods

```bash
kubectl get pods
```

可以查看以上三個 pods 的 log，來看 hello world 有沒有出來。

```bash
kubectl logs hello-kubernetes-7b8d6cd658-9zv26
```

#### 查看服務

```bash
kubectl get svc
```

## 查看 Hello World (目前是 Whitelabel Error Page)

```bash
curl http://localhost:30000
```

## 修改 Hello World 專案以在網頁顯示

```java
package com.example.demo;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
@RestController
public class DemoApplication {

	public static void main(String[] args) {
		SpringApplication.run(DemoApplication.class, args);
	}

	@GetMapping("/")
	public String printHello() {
		return "Hello, World!";
	}
}
```

### 重新建置 Docker 映像

```bash
docker build -t papakao/hello-kubernetes:1.1 .
```

### 將新的映像轉移到 Docker Hub

```bash
docker push papakao/hello-kubernetes:1.1
```

### deployment.yaml 更新版本

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hello-kubernetes
spec:
  replicas: 3
  selector:
    matchLabels:
      app: hello-kubernetes
  template:
    metadata:
      labels:
        app: hello-kubernetes
    spec:
      containers:
        - name: hello-kubernetes
          image: papakao/hello-kubernetes:1.1 # 更新至新版本
          ports:
            - containerPort: 8080
```

### 應用程式更新

```bash
kubectl apply -f deployment.yaml
```

Kubernetes 會自動進行滾動更新，逐步替換舊版本的 Pod 為新版本，而不會導致服務中斷。

### 驗證更新

```bash
kubectl get pods
kubectl get pods --watch
kubectl describe deployments hello-kubernetes
kubectl logs deployments hello-kubernetes
```

## 查看 Hello World

```bash
curl http://localhost:30000
```

## 進階應用與注意事項

- **部署最佳化：** 部署前請確認容器映像已更新，必要時搭配滾動更新確保不中斷服務。
- **資源監控：** 使用 `kubectl get pods --watch` 持續監控資源狀態，及早發現異常。
- **安全性：** 在生產環境中，請確保 API 金鑰、憑證等敏感資訊妥善管理。
