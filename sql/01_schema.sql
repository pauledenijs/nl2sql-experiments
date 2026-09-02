CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE stories (
	story_id SMALLINT PRIMARY KEY,
	title TEXT NOT NULL
);

CREATE TABLE participants (
	participant_id TEXT PRIMARY KEY,
	age INTEGER,
	l2_status SMALLINT NOT NULL,
	session_order INTEGER NOT NULL
);

CREATE TABLE stimuli (
	stimulus_id	INTEGER PRIMARY KEY,
	story_id SMALLINT NOT NULL,
	sentence_num INTEGER NOT NULL,
	word_position INTEGER NOT NULL,
	word TEXT NOT NULL,
	frequency DOUBLE PRECISION NOT NULL,
	length INTEGER NOT NULL,
	surprisal DOUBLE PRECISION NOT NULL,
	condition TEXT,
	
	CONSTRAINT stimuli_story_id_fk
		FOREIGN KEY (story_id)
		REFERENCES stories(story_id)
		ON DELETE RESTRICT
);

CREATE TABLE responses (
	participant_id TEXT,
	stimulus_id INTEGER,
	rt INTEGER NOT NULL,
	onset_ms INTEGER NOT NULL,
	offset_ms INTEGER NOT NULL,
	
	CONSTRAINT responses_pk
		PRIMARY KEY (participant_id, stimulus_id),
	
	CONSTRAINT responses_participant_id_fk
		FOREIGN KEY (participant_id)
		REFERENCES participants (participant_id)
		ON DELETE RESTRICT,
		
	CONSTRAINT responses_stimulus_id_fk
		FOREIGN KEY (stimulus_id)
		REFERENCES stimuli (stimulus_id)
		ON DELETE RESTRICT
);

CREATE TABLE comprehension_questions (
	question_id	INTEGER PRIMARY KEY,
	question TEXT NOT NULL,
	story_id SMALLINT,
	sentence_num INTEGER,
	correct_answer TEXT NOT NULL,
	
	CONSTRAINT comprehension_questions_story_id_fk
	FOREIGN KEY (story_id)
	REFERENCES stories(story_id)
	ON DELETE RESTRICT
);

CREATE TABLE comprehension_responses (
	
	participant_id TEXT,
	response TEXT,
	question_id INTEGER,
	
	CONSTRAINT comprehension_responses_pk
		PRIMARY KEY (participant_id, question_id),
	
	CONSTRAINT comprehension_responses_participant_id_fk
		FOREIGN KEY (participant_id)
		REFERENCES participants (participant_id)
		ON DELETE RESTRICT,
		
	CONSTRAINT comprehension_responses_question_id_fk
		FOREIGN KEY (question_id)
		REFERENCES comprehension_questions(question_id)
		ON DELETE RESTRICT
);

CREATE TABLE codebook(
	table_name TEXT NOT NULL,
	column_name TEXT NOT NULL,
	value TEXT NOT NULL,
	meaning TEXT NOT NULL,
	
	CONSTRAINT codebook_pk
		PRIMARY KEY (table_name, column_name, value)
);