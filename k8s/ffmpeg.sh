cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: ffmpeg-server
  labels:
    app: ffmpeg-server
spec:
  containers:
  - name: ffmpeg
    image: ubuntu:22.04
    command: ["/bin/bash"]
    args: 
      - -c
      - |
        apt-get update && \
        apt-get install -y ffmpeg python3 python3-pip curl && \
        pip3 install flask && \
        mkdir -p /videos && \
        cat > /app.py << 'PYEOF'
        from flask import Flask, request, jsonify
        import subprocess
        import os
        
        app = Flask(__name__)
        UPLOAD_FOLDER = '/videos'
        
        @app.route('/')
        def hello():
            return "FFmpeg Server Ready!"
        
        @app.route('/health')
        def health():
            return jsonify({"status": "healthy"})
        
        @app.route('/ffmpeg-version')
        def version():
            result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
            return f"<pre>{result.stdout}</pre>"
        
        @app.route('/upload', methods=['POST'])
        def upload_file():
            if 'file' not in request.files:
                return jsonify({"error": "No file part"}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({"error": "No selected file"}), 400
            
            filepath = os.path.join(UPLOAD_FOLDER, file.filename)
            file.save(filepath)
            
            return jsonify({
                "message": "File uploaded successfully",
                "filename": file.filename,
                "path": filepath
            })
        
        @app.route('/convert', methods=['POST'])
        def convert_video():
            data = request.json
            input_file = data.get('input')
            output_file = data.get('output', 'output.mp4')
            
            input_path = os.path.join(UPLOAD_FOLDER, input_file)
            output_path = os.path.join(UPLOAD_FOLDER, output_file)
            
            if not os.path.exists(input_path):
                return jsonify({"error": "Input file not found"}), 404
            
            cmd = ['ffmpeg', '-i', input_path, '-c:v', 'libx264', '-crf', '23', output_path, '-y']
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                return jsonify({
                    "message": "Conversion completed",
                    "output": output_file,
                    "ffmpeg_output": result.stderr
                })
            except subprocess.TimeoutExpired:
                return jsonify({"error": "Conversion timeout"}), 500
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        @app.route('/files')
        def list_files():
            files = os.listdir(UPLOAD_FOLDER)
            return jsonify({"files": files})
        
        if __name__ == '__main__':
            app.run(host='0.0.0.0', port=8080)
        PYEOF
        python3 /app.py
    ports:
    - containerPort: 8080
      name: http
---
apiVersion: v1
kind: Service
metadata:
  name: ffmpeg-service
spec:
  selector:
    app: ffmpeg-server
  ports:
  - port: 80
    targetPort: 8080
    protocol: TCP
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ffmpeg-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/proxy-body-size: "500m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - peoplesystem.tatdvsonorth.com
    secretName: ffmpeg-tls
  rules:
  - host: peoplesystem.tatdvsonorth.com
    http:
      paths:
      - path: /ffmpeg
        pathType: Prefix
        backend:
          service:
            name: ffmpeg-service
            port:
              number: 80
EOF