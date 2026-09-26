from dataclasses import dataclass


Number = int | float | None


@dataclass(frozen=True)
class RunnerRatings:
    horse_number: int | None
    horse_name: str
    official_rating: Number = None
    last_winning_rating: Number = None
    speed: Number = None
    form: Number = None
    scope: Number = None
    conditions: Number = None
    trainer_attribute: Number = None
    jockey_attribute: Number = None
    attitude: Number = None
    form_plus: Number = None

    @property
    def form_speed_average(self) -> float | None:
        if self.form is None or self.speed is None:
            return None
        return (self.form + self.speed) / 2

    @property
    def form_minus_speed(self) -> Number:
        if self.form is None or self.speed is None:
            return None
        return self.form - self.speed

    @property
    def form_plus_minus_form(self) -> Number:
        if self.form_plus is None or self.form is None:
            return None
        return self.form_plus - self.form

    @property
    def form_plus_minus_speed(self) -> Number:
        if self.form_plus is None or self.speed is None:
            return None
        return self.form_plus - self.speed