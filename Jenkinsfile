pipeline {
    agent {
        kubernetes {
            yaml '''
                apiVersion: v1
                kind: Pod
                spec:
                  serviceAccountName: jenkins-admin
                  containers:
                  - name: python
                    image: python:3.12
                    command: ["cat"]
                    tty: true
                    volumeMounts:
                    - mountPath: /home/jenkins/agent
                      name: workspace-volume
                    workingDir: /home/jenkins/agent
                  - name: docker
                    image: docker:23-dind
                    privileged: true
                    securityContext:
                      privileged: true
                    env:
                    - name: DOCKER_HOST
                      value: tcp://localhost:2375
                    - name: DOCKER_TLS_CERTDIR
                      value: ""
                    - name: DOCKER_BUILDKIT
                      value: "1"
                    volumeMounts:
                    - mountPath: /home/jenkins/agent
                      name: workspace-volume
                  - name: kubectl
                    image: bitnami/kubectl:1.30.7
                    command: ["/bin/sh"]
                    args: ["-c", "while true; do sleep 30; done"]
                    alwaysPull: true
                    securityContext:
                      runAsUser: 0
                    volumeMounts:
                    - mountPath: /home/jenkins/agent
                      name: workspace-volume
                  volumes:
                  - name: workspace-volume
                    emptyDir: {}
            '''
            defaultContainer 'python'
            inheritFrom 'default'
        }
    }
    options {
        timestamps()
        disableConcurrentBuilds()
    }
    environment {
        DOCKER_IMAGE = 'papakao/maya-sawa'
        DOCKER_TAG = "${BUILD_NUMBER}"
    }
    stages {
        stage('Clone and Setup') {
            steps {
                container('python') {
                    script {
                        withCredentials([
                            string(credentialsId: 'OPENAI_API_KEY', variable: 'OPENAI_API_KEY'),
                            string(credentialsId: 'OPENAI_ORGANIZATION', variable: 'OPENAI_ORGANIZATION'),
                            string(credentialsId: 'DB_HOST', variable: 'DB_HOST'),
                            string(credentialsId: 'DB_PORT', variable: 'DB_PORT'),
                            string(credentialsId: 'DB_DATABASE', variable: 'DB_DATABASE'),
                            string(credentialsId: 'DB_USERNAME', variable: 'DB_USERNAME'),
                            string(credentialsId: 'DB_PASSWORD', variable: 'DB_PASSWORD'),
                            string(credentialsId: 'REDIS_HOST', variable: 'REDIS_HOST'),
                            string(credentialsId: 'REDIS_CUSTOM_PORT', variable: 'REDIS_CUSTOM_PORT'),
                            string(credentialsId: 'REDIS_PASSWORD', variable: 'REDIS_PASSWORD'),
                            string(credentialsId: 'REDIS_QUEUE_MAYA', variable: 'REDIS_QUEUE_MAYA'),
                            string(credentialsId: 'PUBLIC_API_BASE_URL', variable: 'PUBLIC_API_BASE_URL'),
                            string(credentialsId: 'PUBLIC_TYMB_URL', variable: 'PUBLIC_TYMB_URL')
                        ]) {
                            sh '''
                                # 確認 pyproject.toml 存在
                                ls -la
                                if [ ! -f "pyproject.toml" ]; then
                                    echo "Error: pyproject.toml not found!"
                                    exit 1
                                fi
                            '''
                        }
                    }
                }
            }
        }

        stage('Install Dependencies') {
            steps {
                container('python') {
                    sh '''
                        pip install poetry
                        poetry config virtualenvs.create false
                        poetry install --no-root --only main
                    '''
                }
            }
        }

        stage('Build Docker Image with BuildKit') {
            steps {
                container('docker') {
                    script {
                        withCredentials([usernamePassword(credentialsId: 'dockerhub-credentials', usernameVariable: 'DOCKER_USERNAME', passwordVariable: 'DOCKER_PASSWORD')]) {
                            sh '''
                                cd "${WORKSPACE}"
                                echo "${DOCKER_PASSWORD}" | docker login -u "${DOCKER_USERNAME}" --password-stdin
                                # 確認 Dockerfile 存在
                                ls -la
                                if [ ! -f "Dockerfile" ]; then
                                    echo "Error: Dockerfile not found!"
                                    exit 1
                                fi
                                
                                # 構建並推送 Maya Sawa 鏡像
                                docker build \
                                    --build-arg BUILDKIT_INLINE_CACHE=1 \
                                    --cache-from ${DOCKER_IMAGE}:latest \
                                    -t ${DOCKER_IMAGE}:${DOCKER_TAG} \
                                    -t ${DOCKER_IMAGE}:latest \
                                    .
                                docker push ${DOCKER_IMAGE}:${DOCKER_TAG}
                                docker push ${DOCKER_IMAGE}:latest
                            '''
                        }
                    }
                }
            }
        }

        stage('Deploy to Kubernetes') {
            steps {
                container('kubectl') {
                    withKubeConfig([credentialsId: 'kubeconfig-secret']) {
                        script {
                            withCredentials([
                                string(credentialsId: 'OPENAI_API_KEY', variable: 'OPENAI_API_KEY'),
                                string(credentialsId: 'OPENAI_ORGANIZATION', variable: 'OPENAI_ORGANIZATION'),
                                string(credentialsId: 'DB_HOST', variable: 'DB_HOST'),
                                string(credentialsId: 'DB_PORT', variable: 'DB_PORT'),
                                string(credentialsId: 'DB_DATABASE', variable: 'DB_DATABASE'),
                                string(credentialsId: 'DB_USERNAME', variable: 'DB_USERNAME'),
                                string(credentialsId: 'DB_PASSWORD', variable: 'DB_PASSWORD'),
                                string(credentialsId: 'REDIS_HOST', variable: 'REDIS_HOST'),
                                string(credentialsId: 'REDIS_CUSTOM_PORT', variable: 'REDIS_CUSTOM_PORT'),
                                string(credentialsId: 'REDIS_PASSWORD', variable: 'REDIS_PASSWORD'),
                                string(credentialsId: 'REDIS_QUEUE_MAYA', variable: 'REDIS_QUEUE_MAYA'),
                                string(credentialsId: 'PUBLIC_API_BASE_URL', variable: 'PUBLIC_API_BASE_URL'),
                                string(credentialsId: 'PUBLIC_TYMB_URL', variable: 'PUBLIC_TYMB_URL')
                            ]) {
                                withCredentials([usernamePassword(credentialsId: 'dockerhub-credentials', usernameVariable: 'DOCKER_USERNAME', passwordVariable: 'DOCKER_PASSWORD')]) {
                                    script {
                                        try {
                                            sh '''
                                                set -e

                                                # Ensure envsubst is available (try Debian then Alpine)
                                                if ! command -v envsubst >/dev/null 2>&1; then
                                                  (apt-get update && apt-get install -y --no-install-recommends gettext-base ca-certificates) >/dev/null 2>&1 || true
                                                  command -v envsubst >/dev/null 2>&1 || (apk add --no-cache gettext ca-certificates >/dev/null 2>&1 || true)
                                                fi

                                                # In-cluster auth via ServiceAccount (serviceAccountName: jenkins-admin)
                                                kubectl cluster-info

                                                # Ensure Docker Hub imagePullSecret exists in default namespace
                                                kubectl create secret docker-registry dockerhub-credentials \
                                                  --docker-server=https://index.docker.io/v1/ \
                                                  --docker-username="${DOCKER_USERNAME}" \
                                                  --docker-password="${DOCKER_PASSWORD}" \
                                                  --docker-email="none" \
                                                  -n default \
                                                  --dry-run=client -o yaml | kubectl apply -f -

                                                # Inspect manifest directory
                                                ls -la k8s/

                                                echo "Recreating deployment ..."
                                                echo "=== Effective sensitive env values ==="
                                                echo "DB_HOST=${DB_HOST}"
                                                echo "DB_DATABASE=${DB_DATABASE}"
                                                echo "REDIS_HOST=${REDIS_HOST}:${REDIS_CUSTOM_PORT}"

                                                kubectl delete deployment maya-sawa -n default --ignore-not-found
                                                envsubst < k8s/deployment.yaml | kubectl apply -f -
                                                kubectl set image deployment/maya-sawa maya-sawa=${DOCKER_IMAGE}:${DOCKER_TAG} -n default
                                                kubectl rollout status deployment/maya-sawa -n default
                                                
                                                # 部署 CronJob
                                                envsubst < k8s/cronjob.yaml | kubectl apply -f -
                                            '''

                                            // 檢查部署狀態
                                            sh 'kubectl get deployments -n default'
                                            sh 'kubectl rollout status deployment/maya-sawa -n default'
                                        } catch (Exception e) {
                                            echo "Error during deployment: ${e.message}"
                                            // Debug non-ready pods and recent events
                                            sh '''
                                                set +e
                                                echo "=== Debug: pods for maya-sawa ==="
                                                kubectl get pods -n default -l app.kubernetes.io/name=maya-sawa -o wide || true

                                                echo "=== Debug: describe non-ready pods ==="
                                                for p in $(kubectl get pods -n default -l app.kubernetes.io/name=maya-sawa -o jsonpath='{.items[?(@.status.conditions[?(@.type=="Ready")].status!="True")].metadata.name}'); do
                                                  echo "--- $p"
                                                  kubectl describe pod -n default "$p" || true
                                                  echo "=== Last 200 logs for $p ==="
                                                  kubectl logs -n default "$p" --tail=200 || true
                                                done

                                                echo "=== Recent events (default ns) ==="
                                                kubectl get events -n default --sort-by=.lastTimestamp | tail -n 100 || true
                                            '''
                                            throw e
                                        }
                                    } // end script
                                } // end inner withCredentials
                            }
                        }
                    }
                }
            }
        }

        stage('Validate JSON Configs') {
            steps {
                sh '''
                    echo "Validating JSON configuration files..."
                    
                    # 驗證 rules.json
                    python3 -c "import json; json.load(open('maya_sawa/core/rules.json'))"
                    echo "✓ rules.json validated"
                    
                    # 驗證 keywords.json
                    python3 -c "import json; json.load(open('maya_sawa/core/keywords.json'))"
                    echo "✓ keywords.json validated"
                    
                    # 驗證 prompts.json
                    python3 -c "import json; json.load(open('maya_sawa/core/prompts.json'))"
                    echo "✓ prompts.json validated"
                    
                    # 驗證 constants.json
                    python3 -c "import json; json.load(open('maya_sawa/core/constants.json'))"
                    echo "✓ constants.json validated"
                    
                    echo "All JSON configuration files validated successfully"
                '''
            }
        }
    }
    post {
        always {
            cleanWs()
        }
    }
}