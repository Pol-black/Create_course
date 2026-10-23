CREATE TYPE file_type_enum       AS ENUM ('PDF', 'DOCX', 'TXT');
CREATE TYPE document_status_enum AS ENUM ('UPLOADED', 'PROCESSING', 'PROCESSED', 'FAILED');
CREATE TYPE course_status_enum   AS ENUM ('GENERATING', 'READY', 'FAILED');
CREATE TYPE section_status_enum  AS ENUM ('GENERATING', 'READY', 'HAS_ISSUES', 'FAILED');
CREATE TYPE author_enum          AS ENUM ('AI', 'USER');
CREATE TYPE log_level_enum       AS ENUM ('INFO', 'WARN', 'ERROR');

CREATE TABLE document (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_name      TEXT                 NOT NULL,   -- исходное имя файла
    file_type      file_type_enum,
    file_size      BIGINT               CHECK (file_size >= 0),
    file_path      TEXT,
    status         document_status_enum NOT NULL,
    error_message  TEXT,
    check_enabled  BOOLEAN              NOT NULL,
    extracted_text TEXT,
    created_at     TIMESTAMPTZ          NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ          NOT NULL DEFAULT now(),
    
    CONSTRAINT chk_document_file_present CHECK (
        status = 'FAILED'
        OR (file_type IS NOT NULL AND file_size IS NOT NULL AND file_path IS NOT NULL)
    ),
    CONSTRAINT chk_document_error_message CHECK (
        status <> 'FAILED' OR error_message IS NOT NULL
    )
);

-- Фрагмент текста документа
CREATE TABLE chunk (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    position    INT    NOT NULL CHECK (position >= 0),
    heading     TEXT,
    page_from   INT,
    page_to     INT,
    text        TEXT   NOT NULL,
    CONSTRAINT uq_chunk_position UNIQUE (document_id, position),
    CONSTRAINT chk_chunk_pages CHECK (page_from IS NULL OR page_to IS NULL OR page_from <= page_to)
);

-- Курс
CREATE TABLE course (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT             NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    title       TEXT               NOT NULL,
    description TEXT,
    goals       JSONB              NOT NULL CHECK (jsonb_typeof(goals) = 'array'),
    status      course_status_enum NOT NULL,
    error_message TEXT,
    created_at  TIMESTAMPTZ        NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ        NOT NULL DEFAULT now()
);

-- Раздел курса
CREATE TABLE section (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    course_id          BIGINT              NOT NULL REFERENCES course(id) ON DELETE CASCADE,
    position           INT                 NOT NULL CHECK (position >= 0),
    title              TEXT                NOT NULL,
    current_version_id BIGINT,
    status             section_status_enum NOT NULL,
    created_at         TIMESTAMPTZ         NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ         NOT NULL DEFAULT now(),
    CONSTRAINT uq_section_position UNIQUE (course_id, position)
);

-- Версия содержимого раздела
CREATE TABLE section_version (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    section_id   BIGINT      NOT NULL REFERENCES section(id) ON DELETE CASCADE,
    version_no   INT         NOT NULL CHECK (version_no >= 1),
    content      JSONB       NOT NULL,
    author       author_enum NOT NULL,
    model        TEXT,
    prompt_name  TEXT,
    user_hint    TEXT,
    check_result JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_section_version_no UNIQUE (section_id, version_no),
    CONSTRAINT uq_section_version_id_section UNIQUE (id, section_id)
);

-- Текущая версия раздела
ALTER TABLE section
    ADD CONSTRAINT fk_section_current_version
    FOREIGN KEY (current_version_id, id)
    REFERENCES section_version (id, section_id)
    ON DELETE SET NULL (current_version_id);

-- Связь «версия раздела" и "фрагменты-источники"
CREATE TABLE section_version_chunk (
    section_version_id BIGINT NOT NULL REFERENCES section_version(id) ON DELETE CASCADE,
    chunk_id           BIGINT NOT NULL REFERENCES chunk(id)           ON DELETE CASCADE,
    PRIMARY KEY (section_version_id, chunk_id)
);

-- Журнал обработки
CREATE TABLE processing_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT         NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    stage       TEXT           NOT NULL,
    level       log_level_enum NOT NULL,
    message     TEXT           NOT NULL,
    duration_ms INT            CHECK (duration_ms >= 0),
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT now()
);


CREATE INDEX idx_course_document   ON course(document_id);
CREATE INDEX idx_svc_chunk         ON section_version_chunk(chunk_id);
CREATE INDEX idx_log_document      ON processing_log(document_id, created_at);


CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_document_updated_at BEFORE UPDATE ON document
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_course_updated_at   BEFORE UPDATE ON course
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_section_updated_at  BEFORE UPDATE ON section
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
