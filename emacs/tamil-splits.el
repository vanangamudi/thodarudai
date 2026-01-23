;; -*- lexical-binding: t; -*-
(defvar tamil-splits-socket
  (expand-file-name "run/tamil_words.sock" (locate-dominating-file default-directory ".git"))
  "Path to the Unix domain socket exposed by the word server.")

(defun tamil-splits--send (command &optional body-lines)
  "Send COMMAND (string) and optional BODY-LINES (list of strings) to the Unix socket.
Returns a cons (status-line . body-string)."
  (let* ((buf (generate-new-buffer " *tamil-splits-io*"))
         (proc (make-network-process :name "tamil-splits"
                                     :buffer buf
                                     :family 'local
                                     :service tamil-splits-socket)))
    (unless (process-live-p proc)
      (error "Failed to connect to %s" tamil-splits-socket))
    (process-send-string proc (concat command "\n"))
    (when body-lines
      (process-send-string proc (mapconcat (lambda (s) (concat s "\n")) body-lines "")))
    (process-send-eof proc)
    (while (eq (process-status proc) 'open)
      (accept-process-output proc 0.1))
    (with-current-buffer buf
      (goto-char (point-min))
      (let* ((status (buffer-substring-no-properties (line-beginning-position) (line-end-position))))
        (forward-line 1)
        (let ((body (buffer-substring-no-properties (point) (point-max))))
          (kill-buffer buf)
          (cons status body))))))

(defun tamil-splits--percent-encode (s)
  (url-hexify-string (or s "")))

(defun tamil-splits-query (prefix suffix min-len limit exclude-accepted &optional regex)
  "Fetch a TSV batch and display in a new buffer."
  (interactive
   (list (read-string "Prefix: ")
         (read-string "Suffix: ")
         (read-number "Min grapheme length: " 10)
         (read-number "Limit: " 200)
         (y-or-n-p "Exclude accepted? ")
         (let ((r (read-string "Regex (optional): "))) (unless (string-empty-p r) r))))
  (let* ((cmd (format "QUERY prefix=%s suffix=%s min_len=%d limit=%d offset=0 exclude_accepted=%s%s"
                      (tamil-splits--percent-encode prefix)
                      (tamil-splits--percent-encode suffix)
                      min-len limit (if exclude-accepted "1" "0")
                      (if (and regex (not (string-empty-p regex)))
                          (format " regex=%s" (tamil-splits--percent-encode regex))
                        "")))
         (resp (tamil-splits--send cmd))
         (status (car resp))
         (body (cdr resp)))
    (unless (string-prefix-p "OK" status)
      (error "Server error: %s" status))
    (with-current-buffer (get-buffer-create "*Tamil Splits Batch*")
      (erase-buffer)
      (insert body)
      (goto-char (point-min))
      (display-buffer (current-buffer)))))

(defun tamil-splits-set-status (status)
  "Set status column (accepted|ambiguous|rejected|todo) on current line or region."
  (interactive (list (completing-read "Status: " '("accepted" "ambiguous" "rejected" "todo") nil t)))
  (save-excursion
    (let ((beg (if (use-region-p) (region-beginning) (line-beginning-position)))
          (end (if (use-region-p) (region-end) (line-end-position))))
      (goto-char beg)
      (while (< (point) end)
        (let* ((line (buffer-substring (line-beginning-position) (line-end-position)))
               (cols (split-string line "\t")))
          (when (>= (length cols) 5)
            (setf (nth 4 cols) status)
            (delete-region (line-beginning-position) (line-end-position))
            (insert (mapconcat #'identity cols "\t"))))
        (forward-line 1)))))

(defun tamil-splits-set-splits (split-str)
  "Set splits column using plus-separated parts; alternatives separated by ' || '."
  (interactive "sSplits (use + between parts, ' || ' between alternatives): ")
  (save-excursion
    (let ((beg (if (use-region-p) (region-beginning) (line-beginning-position)))
          (end (if (use-region-p) (region-end) (line-end-position))))
      (goto-char beg)
      (while (< (point) end)
        (let* ((line (buffer-substring (line-beginning-position) (line-end-position)))
               (cols (split-string line "\t")))
          (when (>= (length cols) 4)
            (setf (nth 3 cols) split-str)
            (delete-region (line-beginning-position) (line-end-position))
            (insert (mapconcat #'identity cols "\t"))))
        (forward-line 1)))))

(defun tamil-splits-commit (&optional batch-name)
  "POST current TSV buffer to the server ledger over the Unix socket."
  (interactive (list (read-string "Batch name: " (file-name-base (or (buffer-file-name) "batch")))))
  (save-excursion
    (goto-char (point-min))
    (let* ((lines (split-string (buffer-substring-no-properties (point-min) (point-max)) "\n" t))
           (rows (length lines)))
      (unless (> rows 0) (error "Empty buffer"))
      (unless (string-prefix-p "word\tfreq\tglen\t" (car lines))
        (error "First line must be TSV header starting with: word\\tfreq\\tglen"))
      (let* ((cmd (format "COMMIT batch=%s rows=%d" (tamil-splits--percent-encode batch-name) rows))
             (resp (tamil-splits--send cmd lines))
             (status (car resp)))
        (unless (string-prefix-p "OK" status)
          (error "Server error: %s" status))
        (message "%s" status)))))

(global-set-key (kbd "C-c t q") #'tamil-splits-query)
(global-set-key (kbd "C-c t a") (lambda () (interactive) (tamil-splits-set-status "accepted")))
(global-set-key (kbd "C-c t m") (lambda () (interactive) (tamil-splits-set-status "ambiguous")))
(global-set-key (kbd "C-c t r") (lambda () (interactive) (tamil-splits-set-status "rejected")))
(global-set-key (kbd "C-c t s") #'tamil-splits-set-splits)
(global-set-key (kbd "C-c t c") #'tamil-splits-commit)
